package com.example.busbooking.integration;

import org.flywaydb.core.Flyway;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.core.io.ClassPathResource;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.jdbc.datasource.init.ResourceDatabasePopulator;
import org.springframework.test.context.ActiveProfiles;

import javax.sql.DataSource;
import java.math.BigDecimal;
import java.sql.DriverManager;
import java.sql.SQLException;
import java.util.UUID;
import java.util.function.Consumer;

import static org.assertj.core.api.Assertions.assertThat;

@SpringBootTest
@ActiveProfiles("test")
class FlywayUpgradeIntegrationTest {
    @Value("${spring.datasource.url}") String jdbcUrl;
    @Value("${spring.datasource.username}") String username;
    @Value("${spring.datasource.password}") String password;

    @Test
    void upgradesV16DataAndPreservesBookingRelationshipsAndAmounts() throws SQLException {
        withNewDatabase(source -> {
            Flyway throughV16 = Flyway.configure().dataSource(source).target("16").load();
            throughV16.migrate();
            assertThat(throughV16.info().current().getVersion().getVersion()).isEqualTo("16");
            new ResourceDatabasePopulator(new ClassPathResource("fixtures/v16-migration.sql")).execute(source);

            Flyway latest = Flyway.configure().dataSource(source).load();
            assertThat(latest.migrate().migrationsExecuted).isPositive();
            latest.validate();
            var sql = new JdbcTemplate(source);
            assertThat(sql.queryForObject("""
                    SELECT b.total_amount
                    FROM bookings b
                    JOIN users u ON u.id = b.user_id
                    JOIN trips t ON t.id = b.trip_id
                    JOIN roles r ON r.id = u.role_id
                    WHERE b.booking_code = 'V16-FIXTURE'
                        AND u.email = 'upgrade-test@example.com' AND u.email_verified
                        AND r.name = 'USER' AND t.status = 'SCHEDULED' AND t.available_seats = 8
                        AND b.quantity = 2 AND b.status = 'CONFIRMED'
                    """, BigDecimal.class)).isEqualByComparingTo("300000.00");
            assertThat(latest.migrate().migrationsExecuted).isZero();
            assertThat(sql.queryForObject("SELECT count(*) FROM bookings", Long.class)).isEqualTo(1L);
            assertThat(latest.info().pending()).isEmpty();
        });
    }

    @Test
    void installsAndValidatesEveryMigrationOnAnEmptyDatabase() throws SQLException {
        withNewDatabase(source -> {
            Flyway flyway = Flyway.configure().dataSource(source).load();
            assertThat(flyway.migrate().migrationsExecuted).isPositive();
            flyway.validate();
            assertThat(flyway.info().pending()).isEmpty();
            assertThat(new JdbcTemplate(source).queryForObject("SELECT count(*) FROM bookings", Long.class)).isZero();
        });
    }

    private void withNewDatabase(Consumer<DataSource> operation) throws SQLException {
        // Some legacy migrations refer to public explicitly, so a sibling schema is not isolated.
        String name = "bb_migration_" + UUID.randomUUID().toString().replace("-", "");
        String scratchUrl = jdbcUrl.replaceFirst("/[^/?]+(?=\\?|$)", "/" + name);
        if (scratchUrl.equals(jdbcUrl)) {
            throw new IllegalStateException("TEST_DB_URL must include the PostgreSQL database name");
        }
        try (var admin = DriverManager.getConnection(jdbcUrl, username, password);
             var ddl = admin.createStatement()) {
            ddl.execute("CREATE DATABASE " + name + " TEMPLATE template0");
            try {
                operation.accept(new DriverManagerDataSource(scratchUrl, username, password));
            } finally {
                ddl.execute("DROP DATABASE " + name + " WITH (FORCE)");
            }
        }
    }
}
