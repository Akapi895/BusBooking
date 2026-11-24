package com.example.busbooking.security;

import com.example.busbooking.domain.model.RoleChanged;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;
import org.springframework.transaction.event.TransactionPhase;
import org.springframework.transaction.event.TransactionalEventListener;

@Component
public class RoleChangeAudit {
    private static final Logger LOG = LoggerFactory.getLogger(RoleChangeAudit.class);

    @TransactionalEventListener(phase = TransactionPhase.AFTER_COMMIT)
    public void record(RoleChanged event) {
        LOG.info("event=role_changed actorId={} targetId={} previousRole={} newRole={}",
                event.actorId(), event.targetId(), event.previousRole(), event.newRole());
    }
}
