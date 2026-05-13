# UI App

Frontend web application for the Online Banking Demo.

## Purpose

React-based single-page application providing the user interface for banking operations. Includes authentication, account management, transaction history, transfers, budget insights, and AI chatbot integration.

## Technology Stack

- React 19
- TypeScript
- Material-UI (MUI) v9
- React Router (client-side routing)
- Axios (HTTP client)
- Vite (build tool)

## Features

- **Authentication**: Login/register flows with JWT token management
- **Dashboard**: Account overview and balance summaries
- **Transactions**: Transaction history with filtering and search
- **Transfers**: Peer-to-peer and account-to-account transfers
- **Budget Insights**: Spending analysis and category breakdowns
- **AI Chatbot**: Natural language banking assistant
- **Account Opening**: New account application workflow with document upload
- **Admin Panel**: User management and transaction review (admin-only)

## Configuration

### Environment Variables

Create a `.env` file in the root directory:

```env
REACT_APP_API_BASE_URL=http://localhost:6001
REACT_APP_USER_SERVICE_URL=http://localhost:6001
REACT_APP_ACCOUNT_SERVICE_URL=http://localhost:6002
REACT_APP_TRANSACTION_SERVICE_URL=http://localhost:6003
REACT_APP_TRANSFER_SERVICE_URL=http://localhost:6004
REACT_APP_CHATBOT_SERVICE_URL=http://localhost:8001
REACT_APP_AI_SERVICE_URL=http://localhost:8002
REACT_APP_BUDGET_SERVICE_URL=http://localhost:8003
REACT_APP_ACCOUNT_OPENING_SERVICE_URL=http://localhost:8004
```

## Local Development

### Prerequisites
- Node.js 18+
- npm 9+

### Run Locally

```bash
cd src/ui-app
npm install
npm start
```

Application will start on `http://localhost:3000`.

### Build for Production

```bash
npm run build
```

Production build output in `build/` directory.

### Docker

```bash
docker build -t ui-app .
docker run -p 8080:80 ui-app
```

Docker image uses Nginx to serve the static build.

## Testing

```bash
npm test
```

Launches the test runner in interactive watch mode.

### End-to-End Tests

E2E tests are located in `../../tests/e2e` (Playwright).

## Project Structure

```
src/
├── components/       # Reusable React components
├── pages/           # Page-level components (routes)
├── services/        # API client services
├── hooks/           # Custom React hooks
├── contexts/        # React context providers
├── utils/           # Utility functions
├── types/           # TypeScript type definitions
└── App.tsx          # Root component with routing
```

## Notes

- All API calls include JWT token from localStorage
- MUI theming configured for banking brand colors
- React Router handles client-side navigation
- Axios interceptors handle auth errors and token refresh
- Production build served via Nginx on port 80 in Docker
