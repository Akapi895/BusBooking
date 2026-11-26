# Stage 1: Build Java application
FROM maven:3.9-eclipse-temurin-21 AS build

WORKDIR /app

# Dependencies first, so editing src/ does not download them again.
COPY pom.xml .
RUN mvn -B -q dependency:go-offline

COPY src ./src
RUN mvn -B -DskipTests package

# Stage 2: Run Spring Boot
FROM eclipse-temurin:21-jre

WORKDIR /app

# Run without root privileges.
RUN groupadd --system app && useradd --system --gid app --no-create-home app

COPY --from=build /app/target/*.jar app.jar

USER app

EXPOSE 8085

# Size the heap from the container memory limit instead of the JVM's 25% default.
ENTRYPOINT ["java", "-XX:MaxRAMPercentage=75", "-jar", "app.jar"]
