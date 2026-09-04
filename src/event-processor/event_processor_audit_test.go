package main

import (
	"bytes"
	"context"
	"encoding/json"
	"log/slog"
	"strings"
	"testing"

	"github.com/redis/go-redis/v9"
	"go.opentelemetry.io/otel"
)

// Every event type that is actually published onto the banking-events stream.
//
// Verified against the producers, not against a design document:
//   - TransactionCreated, InsufficientFundsAttempt
//     src/transaction-service/Constants.cs EventTypes
//   - TransferInitiated
//     src/transfer-service/Constants.cs EventTypes
//   - UserRegistered, RoleGranted
//     src/user-service/Constants.cs EventTypes
//   - the Approval*/Policy*/Copilot* set
//     docs/design/banker-copilot-policy-engine.md §7.2, published by
//     authority-service (epic #332)
//
// An event type that reaches the default branch is published-but-unaudited,
// which is the exact failure #335 exists to close. Adding a producer without
// adding a case here must fail this test.
var publishedEventTypes = []string{
	"TransactionCreated",
	"InsufficientFundsAttempt",
	"TransferInitiated",
	"UserRegistered",
	"RoleGranted",
	"CopilotSessionStarted",
	"ApprovalProposed",
	"ActionProposalRejected",
	"PolicyEscalated",
	"ApprovalSigned",
	"ApprovalDenied",
	"ApprovalExpired",
	"ApprovalExecuted",
	"ApprovalExecutionFailed",
	"ApprovalVoidedByPolicyChange",
	"PolicyReloaded",
}

func processEventAndCaptureLogs(t *testing.T, eventType string) string {
	t.Helper()

	payload, err := json.Marshal(BankingEvent{
		EventType: eventType,
		Timestamp: "2026-09-04T13:41:02.117Z",
		Data: map[string]interface{}{
			"approvalId":     "apr_01JQ8Z3M4W7K",
			"correlationId":  "0af7651916cd43dd8448eb211c80319c",
			"terminalReason": "TTL_EXPIRED",
		},
	})
	if err != nil {
		t.Fatalf("failed to marshal event: %v", err)
	}

	var buf bytes.Buffer
	previous := slog.Default()
	slog.SetDefault(slog.New(slog.NewJSONHandler(&buf, &slog.HandlerOptions{Level: slog.LevelDebug})))
	defer slog.SetDefault(previous)

	p := &EventProcessor{tracer: otel.Tracer("test")}

	msg := redis.XMessage{
		ID:     "1-0",
		Values: map[string]interface{}{"payload": string(payload)},
	}

	if err := p.processMessage(context.Background(), msg); err != nil {
		t.Fatalf("processMessage returned an error for %s: %v", eventType, err)
	}

	return buf.String()
}

func TestEveryPublishedEventTypeIsAudited(t *testing.T) {
	for _, eventType := range publishedEventTypes {
		t.Run(eventType, func(t *testing.T) {
			logs := processEventAndCaptureLogs(t, eventType)

			if strings.Contains(logs, "Unknown event type") {
				t.Errorf("%s fell through to the unknown-event branch — it is published but unaudited", eventType)
			}
			if !strings.Contains(logs, "Audit "+eventType) {
				t.Errorf("expected an %q audit line, got: %s", "Audit "+eventType, logs)
			}
		})
	}
}

func TestGenuinelyUnknownEventStillWarns(t *testing.T) {
	// The default branch must survive: an event type nobody has taught this
	// consumer about should still be loud, not silently dropped.
	logs := processEventAndCaptureLogs(t, "SomethingNobodyDeclared")

	if !strings.Contains(logs, "Unknown event type") {
		t.Errorf("expected the unknown-event warning, got: %s", logs)
	}
}

func TestTerminalReasonIsLoggedForAuthorityEvents(t *testing.T) {
	// status == "denied" is a single bucket covering human refusals, timeouts,
	// policy escalations and re-plans. An audit line that records the status
	// without terminalReason is wrong roughly one time in four, so the reason
	// must be present on the record.
	logs := processEventAndCaptureLogs(t, "ApprovalExpired")

	if !strings.Contains(logs, "terminal_reason") {
		t.Errorf("ApprovalExpired audit line must carry terminal_reason, got: %s", logs)
	}
	if !strings.Contains(logs, "TTL_EXPIRED") {
		t.Errorf("ApprovalExpired audit line must carry the TTL_EXPIRED reason, got: %s", logs)
	}
}
