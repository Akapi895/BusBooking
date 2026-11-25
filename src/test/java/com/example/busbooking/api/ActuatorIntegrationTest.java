package com.example.busbooking.api;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.context.ActiveProfiles;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import static org.assertj.core.api.Assertions.assertThat;

@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
@ActiveProfiles("test")
class ActuatorIntegrationTest {
    private final HttpClient http = HttpClient.newHttpClient();
    @Value("${local.server.port}") int apiPort;
    @Value("${local.management.port}") int managementPort;

    @Test
    void managementPortServesHealthAndHikariMetrics() throws Exception {
        var health = get(managementPort, "/actuator/health");
        assertThat(health.statusCode()).isEqualTo(200);
        assertThat(health.body()).contains("\"UP\"");

        var pool = get(managementPort, "/actuator/metrics/hikaricp.connections.max");
        assertThat(pool.statusCode()).isEqualTo(200);
        assertThat(pool.body()).contains("hikaricp.connections.max");
        assertThat(get(managementPort, "/actuator/metrics/hikaricp.connections.pending").statusCode()).isEqualTo(200);
    }

    @Test
    void apiPortDoesNotExposeActuator() throws Exception {
        assertThat(get(apiPort, "/actuator/health").statusCode()).isNotEqualTo(200);
        assertThat(get(apiPort, "/actuator/metrics").statusCode()).isNotEqualTo(200);
    }

    private HttpResponse<String> get(int port, String path) throws Exception {
        return http.send(HttpRequest.newBuilder(URI.create("http://127.0.0.1:" + port + path)).build(),
                HttpResponse.BodyHandlers.ofString());
    }
}
