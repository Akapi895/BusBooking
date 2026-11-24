"""Owned Linux/Kaggle processes only. Never attaches to an existing database/app."""
import base64
import json
import os
from pathlib import Path
import platform
import secrets
import shutil
import socket
import subprocess
import tarfile
import time
import urllib.request
import zipfile

import psycopg
from psycopg import sql
import requests

from .common import digest, effective_cpus, save, cgroup_snapshot


class Runtime:
    def __init__(self, root, jar, config):
        self.root, self.jar, self.config = Path(root).resolve(), Path(jar).resolve(), config
        self.root.mkdir(parents=True, exist_ok=False)
        self.db = "bb_" + secrets.token_hex(6)
        self.role = self.db
        self.password = secrets.token_urlsafe(24)
        self.secret = base64.b64encode(secrets.token_bytes(32)).decode()
        self.otp_secret = base64.b64encode(secrets.token_bytes(32)).decode()
        self.app = self.mail = None
        self.pg_started = False
        self.pgdir = Path("/tmp") / (self.db + "_pg")
        self.jdk = self.root / "jdk"
        self.logs = self.root / "logs"
        self.logs.mkdir()
        self.app_port = int(config["runtime"]["port"])
        self.pg_port = int(config["runtime"]["pg_port"])
        self.url = f"http://127.0.0.1:{self.app_port}"
        self.dsn = {"host": "127.0.0.1", "port": self.pg_port, "dbname": self.db,
                    "user": self.role, "password": self.password, "connect_timeout": 5,
                    "application_name": "acceptance_observer"}

    def command(self, args, **kwargs):
        return subprocess.run([str(x) for x in args], check=True, **kwargs)

    def pg_command(self, args, **kwargs):
        prefix = ["runuser", "-u", "postgres", "--"] if os.geteuid() == 0 else []
        return self.command(prefix + [str(x) for x in args], **kwargs)

    @staticmethod
    def free_port(port):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", port))

    def setup(self):
        if platform.system() != "Linux":
            raise RuntimeError("The owned runtime requires Linux; use Kaggle for live acceptance")
        for port in (self.app_port, self.pg_port, 1025, 8025):
            self.free_port(port)  # Never re-use another person's service.
        if self.config["runtime"].get("pg_bin"):
            self.pgbin = Path(self.config["runtime"]["pg_bin"]).resolve()
            if not (self.pgbin / "initdb").is_file():
                raise RuntimeError("Explicit runtime.pg_bin has no initdb")
        else:
            if not list(Path("/usr/lib/postgresql").glob("*/bin/initdb")):
                # Only binary packages are needed; an inherited Kaggle deb-src entry may lack Sources.
                self.command(["apt-get", "-o", "Acquire::IndexTargets::deb-src::Sources::DefaultEnabled=false",
                              "update", "-qq"])
                self.command(["apt-get", "install", "-y", "-qq", "postgresql"],
                             env=dict(os.environ, DEBIAN_FRONTEND="noninteractive"))
            self.pgbin = sorted(Path("/usr/lib/postgresql").glob("*/bin/initdb"),
                                key=lambda p: int(p.parents[1].name))[-1].parent
        self.pgdir = Path(self.config["runtime"].get("pg_work_root", "/tmp")) / (self.db + "_pg")
        self.pgdir.mkdir(mode=0o700)
        if os.geteuid() == 0:
            import pwd
            account = pwd.getpwnam("postgres")
            os.chown(self.pgdir, account.pw_uid, account.pw_gid)
        self.pg_command([self.pgbin / "initdb", "-D", self.pgdir / "data", "-A", "trust", "-U", "postgres"],
                        stdout=subprocess.DEVNULL)
        self.pg_command([self.pgbin / "pg_ctl", "-D", self.pgdir / "data", "-l", self.pgdir / "server.log",
                         "-o", f"-p {self.pg_port} -h 127.0.0.1 -k {self.pgdir}", "-w", "start"],
                        stdout=subprocess.DEVNULL)
        self.pg_started = True
        with self.admin() as conn:
            conn.execute(sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(
                sql.Identifier(self.role), sql.Literal(self.password)))
            conn.execute(sql.SQL("CREATE DATABASE {} OWNER {}").format(
                sql.Identifier(self.db), sql.Identifier(self.role)))
        self.install_java()
        self.install_mailpit()
        self.start_mail()
        self.start_app()
        self.manifest()

    def admin(self):
        return psycopg.connect(host="127.0.0.1", port=self.pg_port, dbname="postgres", user="postgres",
                               autocommit=True, connect_timeout=5)

    def connect(self, **kwargs):
        return psycopg.connect(**self.dsn, **kwargs)

    def install_java(self):
        java_home = os.environ.get("JAVA_HOME")
        if java_home and (Path(java_home) / "bin/jcmd").exists():
            self.jdk = Path(java_home)
            version = subprocess.run([str(self.jdk / "bin/java"), "-version"], capture_output=True, text=True)
            if 'version "21.' in version.stderr:
                return
        self.jdk = self.root / "jdk"
        self.jdk.mkdir()
        archive = self.root / "java.tar.gz"
        urllib.request.urlretrieve("https://corretto.aws/downloads/latest/amazon-corretto-21-x64-linux-jdk.tar.gz", archive)
        # Downloaded tools are trusted upstream inputs; still reject archive traversal/symlinks.
        with tarfile.open(archive) as tar:
            for member in tar.getmembers():
                if not member.isfile():
                    continue
                pieces = Path(member.name).parts[1:]
                destination = self.jdk.joinpath(*pieces).resolve()
                if not destination.is_relative_to(self.jdk.resolve()):
                    raise ValueError("Unsafe JDK archive")
                destination.parent.mkdir(parents=True, exist_ok=True)
                with tar.extractfile(member) as source, open(destination, "wb") as target:
                    shutil.copyfileobj(source, target)
                destination.chmod(member.mode & 0o777)
        archive.unlink()

    def install_mailpit(self):
        archive = self.root / "mailpit.tar.gz"
        version = self.config["runtime"]["mailpit_version"]
        urllib.request.urlretrieve(f"https://github.com/axllent/mailpit/releases/download/{version}/mailpit-linux-amd64.tar.gz", archive)
        self.mail_binary = self.root / "mailpit"
        with tarfile.open(archive) as tar:
            member = next(m for m in tar.getmembers() if m.isfile() and Path(m.name).name == "mailpit")
            with tar.extractfile(member) as source, open(self.mail_binary, "wb") as target:
                shutil.copyfileobj(source, target)
        self.mail_binary.chmod(0o755)
        archive.unlink()

    def start_mail(self):
        with open(self.logs / "mailpit.log", "ab") as log:
            self.mail = subprocess.Popen([str(self.mail_binary), "--listen", "127.0.0.1:8025",
                                           "--smtp", "127.0.0.1:1025"], stdout=log, stderr=log)
        self.wait_http("http://127.0.0.1:8025/api/v1/messages", self.mail)

    def app_env(self):
        # Strip inherited Spring/DB/auth overrides: the declared baseline must be reproducible.
        prefixes = ("SPRING_", "SERVER_", "DB_", "TEST_DB_", "JWT_", "EMAIL_", "SMTP_", "AUTH_",
                    "BOOTSTRAP_", "JAVA_TOOL_OPTIONS", "JDK_JAVA_OPTIONS", "_JAVA_OPTIONS")
        env = {k: v for k, v in os.environ.items() if not k.startswith(prefixes)}
        env.update(SPRING_PROFILES_ACTIVE="dev", SERVER_PORT=str(self.app_port),
                   DB_URL=f"jdbc:postgresql://127.0.0.1:{self.pg_port}/{self.db}",
                   DB_USERNAME=self.role, DB_PASSWORD=self.password,
                   JWT_SECRET=self.secret, EMAIL_OTP_SECRET=self.otp_secret,
                   SPRING_MAIL_HOST="127.0.0.1", SMTP_PORT="1025", BOOTSTRAP_SUPER_ADMIN_ENABLED="false")
        return env

    def start_app(self):
        with open(self.logs / "backend.log", "ab") as log:
            self.app = subprocess.Popen([str(self.jdk / "bin/java"), *self.config["runtime"]["jvm_args"],
                                         "-jar", str(self.jar)], env=self.app_env(), stdout=log, stderr=log)
        self.wait_http(self.url + "/api/trips", self.app)

    def wait_http(self, url, proc):
        end = time.monotonic() + self.config["runtime"]["startup_timeout"]
        while time.monotonic() < end:
            if proc.poll() is not None:
                raise RuntimeError("Owned process exited during startup; inspect logs")
            try:
                if requests.get(url, timeout=3).status_code == 200:
                    return
            except requests.RequestException:
                pass
            time.sleep(1)
        raise RuntimeError("Startup did not reach HTTP 200")

    @staticmethod
    def stop(proc):
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=20)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=10)

    def restart_app(self):
        self.stop(self.app)
        self.start_app()

    def snapshot(self):
        self.stop(self.app)
        env = os.environ.copy()
        env["PGPASSWORD"] = self.password
        self.command([self.pgbin / "pg_dump", "-h", "127.0.0.1", "-p", self.pg_port, "-U", self.role,
                      "-d", self.db, "-Fc", "--no-owner", "-f", self.root / "baseline.dump"], env=env)
        self.start_app()

    def restore(self):
        self.stop(self.app)
        with self.admin() as conn:
            conn.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=%s", (self.db,))
            conn.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(self.db)))
            conn.execute(sql.SQL("CREATE DATABASE {} OWNER {}").format(sql.Identifier(self.db), sql.Identifier(self.role)))
        env = os.environ.copy()
        env["PGPASSWORD"] = self.password
        self.command([self.pgbin / "pg_restore", "-h", "127.0.0.1", "-p", self.pg_port, "-U", self.role,
                      "-d", self.db, "--no-owner", "--exit-on-error", self.root / "baseline.dump"], env=env)
        self.start_app()

    def manifest(self):
        from importlib.metadata import version, distributions
        with self.connect() as conn:
            settings = conn.execute("SELECT name,setting,unit FROM pg_settings WHERE name IN "
                "('max_connections','shared_buffers','work_mem','max_locks_per_transaction','TimeZone','server_version')").fetchall()
            migrations = conn.execute('SELECT version,description,checksum,success FROM flyway_schema_history ORDER BY installed_rank').fetchall()
        manifest = {"jar_sha256": digest(self.jar), "jar_name": self.jar.name,
                    "source_commit": None, "source_commit_authority": "not recoverable from JAR unless supplied separately",
                    "java": subprocess.run([str(self.jdk / "bin/java"), "-version"], capture_output=True, text=True).stderr,
                    "jdk_binary_sha256": digest(self.jdk / ("bin/java.exe" if os.name == "nt" else "bin/java")), "jvm_args": self.config["runtime"]["jvm_args"],
                    "packages": {n: version(n) for n in ("locust", "psutil", "psycopg", "requests", "PyYAML", "bcrypt")},
                    "dependency_inventory": {d.metadata["Name"]: d.version for d in distributions()},
                    "cpu": effective_cpus(), "cgroup": cgroup_snapshot(), "platform": platform.platform(), "postgres": settings,
                    "migrations": migrations, "topology": "Java, PostgreSQL and generator colocated; backend-only capacity unproven",
                    "secret_policy": "ephemeral credentials; performance JWTs minted with current HS256 sub/iss/iat/exp contract; HTTP login tested separately"}
        save(self.root / "environment.json", manifest)

    def close(self):
        self.stop(self.app)
        self.stop(self.mail)
        if self.pg_started:
            try:
                shutil.copy2(self.pgdir / "server.log", self.logs / "postgres.log")
            except OSError:
                pass  # Log export failure must never bypass shutdown of the owned cluster.
            try:
                self.pg_command([self.pgbin / "pg_ctl", "-D", self.pgdir / "data", "-m", "fast", "-w", "stop"],
                                stdout=subprocess.DEVNULL)
                self.pg_started = False
            except Exception:
                # Retain ownership uncertainty rather than asserting that shutdown succeeded.
                raise
