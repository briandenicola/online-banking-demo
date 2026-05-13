import React, { Component, ErrorInfo, ReactNode } from 'react';
import { Box, Button, Container, Paper, Typography } from '@mui/material';
import ErrorOutlineIcon from '@mui/icons-material/ErrorOutlineRounded';

interface ErrorBoundaryProps {
  children: ReactNode;
  /** Optional section name shown in the fallback UI */
  section?: string;
  /** Optional custom fallback — overrides the default UI */
  fallback?: ReactNode;
}

interface ErrorBoundaryState {
  hasError: boolean;
  error: Error | null;
}

class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  constructor(props: ErrorBoundaryProps) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo): void {
    console.error(
      `[ErrorBoundary${this.props.section ? ` — ${this.props.section}` : ''}] Uncaught error:`,
      error,
      errorInfo.componentStack
    );
  }

  handleReset = (): void => {
    this.setState({ hasError: false, error: null });
  };

  render(): ReactNode {
    if (!this.state.hasError) {
      return this.props.children;
    }

    if (this.props.fallback) {
      return this.props.fallback;
    }

    const sectionLabel = this.props.section
      ? `in ${this.props.section}`
      : '';

    return (
      <Container maxWidth="sm" sx={{ py: 8 }}>
        <Paper
          elevation={1}
          sx={{
            p: 5,
            textAlign: 'center',
            borderRadius: 3,
            border: '1px solid',
            borderColor: 'divider',
          }}
        >
          <ErrorOutlineIcon
            sx={{ fontSize: 56, color: 'warning.main', mb: 2 }}
          />

          <Typography variant="h5" gutterBottom>
            Something went wrong
          </Typography>

          <Typography variant="body1" color="text.secondary" sx={{ mb: 1 }}>
            We encountered an unexpected issue{sectionLabel ? ` ${sectionLabel}` : ''}.
            Your accounts and data are safe.
          </Typography>

          <Typography
            variant="body2"
            color="text.secondary"
            sx={{ mb: 4 }}
          >
            You can try again, or return to the dashboard if the problem
            persists.
          </Typography>

          <Box sx={{ display: 'flex', justifyContent: 'center', gap: 2 }}>
            <Button
              variant="contained"
              color="primary"
              onClick={this.handleReset}
            >
              Try Again
            </Button>

            <Button
              variant="outlined"
              color="primary"
              href="/"
            >
              Go to Dashboard
            </Button>
          </Box>
        </Paper>
      </Container>
    );
  }
}

export default ErrorBoundary;
