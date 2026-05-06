# Scripts

## seed-data.sh

Populates the local development environment with demo users, accounts, and transactions.

### Prerequisites

- All services running via Docker Compose:
  ```bash
  docker-compose up -d
  ```
- Services healthy and accepting requests on ports 6001–6004

### Usage

```bash
./scripts/seed-data.sh
```

### What It Creates

| Resource      | Details                                              |
|---------------|------------------------------------------------------|
| **Users**     | alice, bob, admin (password: `Password123!`)         |
| **Accounts**  | Checking + Savings for alice & bob; Checking for admin |
| **Transactions** | Deposits, withdrawals across multiple categories  |
| **Transfers** | Sample transfer from Alice → Bob                     |

### Notes

- The script is **idempotent** for user registration — re-running it won't fail if users already exist.
- Account and transaction creation will add duplicates on re-run (services don't enforce uniqueness on those).
- No external dependencies beyond `curl` and `grep`.
