package com.hashicorp.transitdemo;

import java.time.LocalTime;
import java.time.format.DateTimeFormatter;
import java.util.UUID;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.scheduling.annotation.EnableScheduling;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;
import org.springframework.vault.authentication.LifecycleAwareSessionManager;
import org.springframework.vault.authentication.SessionManager;
import org.springframework.vault.core.VaultOperations;
import org.springframework.vault.core.VaultTemplate;

@SpringBootApplication
@EnableScheduling
@EnableConfigurationProperties(TransitProperties.class)
public class TransitDemoApplication {

    public static void main(String[] args) {
        SpringApplication.run(TransitDemoApplication.class, args);
    }
}

@ConfigurationProperties(prefix = "transit")
record TransitProperties(String path, String key, long intervalMs) {
}

@Component
class VaultTransit {
    private final VaultOperations vault;
    private final TransitProperties props;

    VaultTransit(VaultTemplate vaultTemplate, TransitProperties props) {
        this.vault = vaultTemplate;
        this.props = props;
    }

    String encrypt(String plaintext) {
        return vault.opsForTransit(props.path()).encrypt(props.key(), plaintext);
    }

    String decrypt(String ciphertext) {
        return vault.opsForTransit(props.path()).decrypt(props.key(), ciphertext);
    }
}

@Component
class TransitLoop {
    private static final DateTimeFormatter CLOCK = DateTimeFormatter.ofPattern("HH:mm:ss");

    private final VaultTransit transit;
    private final SessionManager sessionManager;
    private final AtomicInteger seq = new AtomicInteger();
    private final AtomicReference<String> lastToken = new AtomicReference<>("");

    TransitLoop(VaultTransit transit, SessionManager sessionManager) {
        this.transit = transit;
        this.sessionManager = sessionManager;
    }

    @Scheduled(fixedDelayString = "${transit.interval-ms:20000}")
    public void tick() {
        int n = seq.incrementAndGet();
        try {
            roundtrip(n);
        } catch (RuntimeException ex) {
            System.out.println("[" + now() + "] Vault rejected the token (" + ex.getMessage()
                    + "); re-login");
            relogin();
            roundtrip(n);
        }
    }

    private void roundtrip(int n) {
        String token = sessionManager.getSessionToken().getToken();
        noteIfRotated(token);
        String plaintext = "java-" + n + "-" + UUID.randomUUID().toString().substring(0, 8);
        String ciphertext = transit.encrypt(plaintext);
        String decrypted = transit.decrypt(ciphertext);
        if (!plaintext.equals(decrypted)) {
            throw new IllegalStateException("decrypt mismatch");
        }
        System.out.println("[" + now() + "] OK seq=" + n + " token=" + fingerprint(token)
                + " plain=" + plaintext + " cipher=" + ciphertext.substring(0, Math.min(36, ciphertext.length()))
                + "...");
    }

    private void relogin() {
        if (sessionManager instanceof LifecycleAwareSessionManager lifecycle) {
            lifecycle.destroy();
        }
        sessionManager.getSessionToken();
    }

    private void noteIfRotated(String token) {
        String previous = lastToken.getAndSet(token);
        if (previous != null && !previous.isEmpty() && !previous.equals(token)) {
            System.out.println("[" + now() + "] NEW TOKEN previous=" + fingerprint(previous)
                    + " current=" + fingerprint(token));
        } else if (previous == null || previous.isEmpty()) {
            System.out.println("[" + now() + "] LOGIN token=" + fingerprint(token));
        }
    }

    private static String fingerprint(String token) {
        if (token == null || token.isEmpty()) {
            return "<none>";
        }
        return token.substring(0, Math.min(28, token.length())) + "...";
    }

    private static String now() {
        return LocalTime.now().format(CLOCK);
    }
}
