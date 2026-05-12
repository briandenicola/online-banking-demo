# Decision: Option C — Move Balance Updates Into Transaction-Service

**Date:** 2026-05-12  
**Author:** Basher (Backend Dev)  
**Status:** Implemented  
**Priority:** P0  

## Context

Transaction-service previously called account-service via HTTP to validate and update account balances during transaction creation. During transfers, the sender's JWT was forwarded, but account-service's ownership check rejected credit transactions to the destination account because the sender doesn't own it. This is a fundamental service-identity problem with JWT forwarding.

## Decision

Brian chose **Option C**: transaction-service now reads/writes account balances directly in Cosmos DB (same database, accounts container), bypassing the HTTP call to account-service entirely.

## Changes

- Transaction-service gets a second Cosmos container reference (`_accountsContainer`) via `CosmosDb:AccountsContainerName` config
- `ValidateBalanceAsync` and `UpdateAccountBalanceAsync` replaced HTTP calls with direct Cosmos reads/writes
- Removed `IHttpClientFactory`, `IHttpContextAccessor` dependencies from both `TransactionService` and `InMemoryTransactionService`
- `InMemoryTransactionService` uses a local `ConcurrentDictionary<string, decimal>` for account balances
- Account-service's `POST /api/accounts/{id}/balance` endpoint remains but is no longer called by transaction-service
- Transfer-service is unchanged — it still calls transaction-service via HTTP to create debit/credit transactions

## Impact

- Eliminates the service-identity/JWT ownership problem for transfers
- Reduces inter-service HTTP latency for balance operations
- Transaction-service now has direct write access to the accounts container (acceptable tradeoff for atomicity)
- All 11 transaction-service tests pass; no regressions in other services
