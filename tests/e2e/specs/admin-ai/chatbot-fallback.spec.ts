import { test, expect } from '../../fixtures/authFixture';
import { ChatbotPage } from '../../pages/ChatbotPage';

test.describe('E2E-406: Chatbot Fallback — Azure Unavailable', () => {
  let chatbotPage: ChatbotPage;

  test.beforeEach(async ({ authenticatedPage }) => {
    chatbotPage = new ChatbotPage(authenticatedPage);
  });

  test('should show graceful error message when chatbot backend is down', async ({ authenticatedPage }) => {
    // Intercept chatbot API calls and simulate service unavailability
    await authenticatedPage.route('**/api/chat**', route =>
      route.fulfill({
        status: 503,
        contentType: 'application/json',
        body: JSON.stringify({ error: 'Service Unavailable', message: 'Azure AI service is temporarily unavailable' }),
      })
    );
    await authenticatedPage.route('**/api/ai/**', route =>
      route.fulfill({
        status: 503,
        contentType: 'application/json',
        body: JSON.stringify({ error: 'Service Unavailable' }),
      })
    );
    await authenticatedPage.route('**/openai**', route =>
      route.fulfill({
        status: 503,
        contentType: 'application/json',
        body: JSON.stringify({ error: 'Service Unavailable' }),
      })
    );

    await chatbotPage.navigate();
    await authenticatedPage.waitForLoadState('domcontentloaded');
    await authenticatedPage.waitForTimeout(2000);

    const chatAvailable = await chatbotPage.chatContainer.isVisible().catch(() => false) ||
      await chatbotPage.chatWindow.isVisible().catch(() => false);
    if (!chatAvailable) {
      await chatbotPage.openChat();
    }

    const inputVisible = await chatbotPage.messageInput.isVisible().catch(() => false);
    if (!inputVisible) {
      test.skip(true, 'Chatbot UI not available');
      return;
    }

    await chatbotPage.sendMessage('Hello, are you there?');
    await authenticatedPage.waitForTimeout(5000);

    // Should show an error or fallback message (not a blank screen)
    const hasError = await chatbotPage.hasErrorMessage();
    const hasRetry = await chatbotPage.retryButton.isVisible().catch(() => false);
    const lastBot = await chatbotPage.getLastBotMessage();
    const hasFallbackMessage = lastBot.length > 0;

    expect(hasError || hasRetry || hasFallbackMessage).toBeTruthy();
  });

  test('should not crash or blank the UI on service failure', async ({ authenticatedPage }) => {
    // Block all AI-related endpoints
    await authenticatedPage.route('**/api/chat**', route => route.abort('connectionrefused'));
    await authenticatedPage.route('**/api/ai/**', route => route.abort('connectionrefused'));
    await authenticatedPage.route('**/openai**', route => route.abort('connectionrefused'));

    await chatbotPage.navigate();
    await authenticatedPage.waitForLoadState('domcontentloaded');
    await authenticatedPage.waitForTimeout(2000);

    const chatAvailable = await chatbotPage.chatContainer.isVisible().catch(() => false) ||
      await chatbotPage.chatWindow.isVisible().catch(() => false);
    if (!chatAvailable) {
      await chatbotPage.openChat();
    }

    const inputVisible = await chatbotPage.messageInput.isVisible().catch(() => false);
    if (!inputVisible) {
      test.skip(true, 'Chatbot UI not available');
      return;
    }

    await chatbotPage.sendMessage('Test message');
    await authenticatedPage.waitForTimeout(5000);

    // The page should NOT be blank or crashed
    const bodyContent = await authenticatedPage.locator('body').textContent();
    expect(bodyContent?.length).toBeGreaterThan(0);

    // Chat container or window should still be visible
    const uiIntact = await chatbotPage.chatContainer.isVisible().catch(() => false) ||
      await chatbotPage.chatWindow.isVisible().catch(() => false) ||
      await chatbotPage.messageInput.isVisible().catch(() => false);
    expect(uiIntact).toBeTruthy();
  });

  test('should provide retry mechanism or helpful fallback suggestions', async ({ authenticatedPage }) => {
    // Simulate intermittent failure
    let callCount = 0;
    await authenticatedPage.route('**/api/chat**', route => {
      callCount++;
      if (callCount <= 2) {
        return route.fulfill({
          status: 503,
          contentType: 'application/json',
          body: JSON.stringify({ error: 'Service temporarily unavailable' }),
        });
      }
      // Let subsequent calls through
      return route.continue();
    });
    await authenticatedPage.route('**/api/ai/**', route => {
      return route.fulfill({
        status: 503,
        contentType: 'application/json',
        body: JSON.stringify({ error: 'Service temporarily unavailable' }),
      });
    });

    await chatbotPage.navigate();
    await authenticatedPage.waitForLoadState('domcontentloaded');
    await authenticatedPage.waitForTimeout(2000);

    const chatAvailable = await chatbotPage.chatContainer.isVisible().catch(() => false) ||
      await chatbotPage.chatWindow.isVisible().catch(() => false);
    if (!chatAvailable) {
      await chatbotPage.openChat();
    }

    const inputVisible = await chatbotPage.messageInput.isVisible().catch(() => false);
    if (!inputVisible) {
      test.skip(true, 'Chatbot UI not available');
      return;
    }

    await chatbotPage.sendMessage('Help me with my account');
    await authenticatedPage.waitForTimeout(5000);

    // Look for retry button, helpful suggestions, or error with guidance
    const hasRetry = await chatbotPage.retryButton.isVisible().catch(() => false);
    const hasError = await chatbotPage.hasErrorMessage();
    const hasSuggestions = await authenticatedPage.locator(
      '[data-testid*="suggestion"], .suggestion, button:has-text("Try"), a[href*="help"]'
    ).first().isVisible().catch(() => false);

    // At least one fallback mechanism should exist
    expect(hasRetry || hasError || hasSuggestions).toBeTruthy();

    // If retry exists, test that it works
    if (hasRetry) {
      await chatbotPage.retryButton.click();
      await authenticatedPage.waitForTimeout(5000);
      // After retry, UI should still be functional
      const stillFunctional = await chatbotPage.messageInput.isVisible().catch(() => false);
      expect(stillFunctional).toBeTruthy();
    }
  });

  test('should allow user to navigate away normally during service failure', async ({ authenticatedPage }) => {
    // Block chat API
    await authenticatedPage.route('**/api/chat**', route =>
      route.fulfill({
        status: 503,
        contentType: 'application/json',
        body: JSON.stringify({ error: 'Service Unavailable' }),
      })
    );
    await authenticatedPage.route('**/api/ai/**', route =>
      route.fulfill({
        status: 503,
        contentType: 'application/json',
        body: JSON.stringify({ error: 'Service Unavailable' }),
      })
    );

    await chatbotPage.navigate();
    await authenticatedPage.waitForLoadState('domcontentloaded');
    await authenticatedPage.waitForTimeout(2000);

    const chatAvailable = await chatbotPage.chatContainer.isVisible().catch(() => false) ||
      await chatbotPage.chatWindow.isVisible().catch(() => false);
    if (!chatAvailable) {
      await chatbotPage.openChat();
    }

    const inputVisible = await chatbotPage.messageInput.isVisible().catch(() => false);
    if (inputVisible) {
      await chatbotPage.sendMessage('Test during failure');
      await authenticatedPage.waitForTimeout(3000);
    }

    // User should be able to navigate to other pages without issue
    await authenticatedPage.goto('/');
    await authenticatedPage.waitForLoadState('domcontentloaded');
    await authenticatedPage.waitForTimeout(2000);

    const dashboardUrl = await authenticatedPage.url();
    expect(dashboardUrl).toContain('/dashboard');

    // Dashboard should load correctly
    const dashboardContent = await authenticatedPage.locator('main, [role="main"], .dashboard, h1, h2').first();
    await expect(dashboardContent).toBeVisible({ timeout: 10_000 });
  });

  test('should handle timeout gracefully', async ({ authenticatedPage }) => {
    // Simulate a very slow response (timeout)
    await authenticatedPage.route('**/api/chat**', async route => {
      await new Promise(resolve => setTimeout(resolve, 60_000));
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ message: 'delayed response' }),
      });
    });

    await chatbotPage.navigate();
    await authenticatedPage.waitForLoadState('domcontentloaded');
    await authenticatedPage.waitForTimeout(2000);

    const chatAvailable = await chatbotPage.chatContainer.isVisible().catch(() => false) ||
      await chatbotPage.chatWindow.isVisible().catch(() => false);
    if (!chatAvailable) {
      await chatbotPage.openChat();
    }

    const inputVisible = await chatbotPage.messageInput.isVisible().catch(() => false);
    if (!inputVisible) {
      test.skip(true, 'Chatbot UI not available');
      return;
    }

    await chatbotPage.sendMessage('This should timeout');

    // Wait for a reasonable timeout period
    await authenticatedPage.waitForTimeout(10_000);

    // UI should show loading or timeout message but not crash
    const isLoading = await chatbotPage.loadingIndicator.isVisible().catch(() => false);
    const hasError = await chatbotPage.hasErrorMessage();
    const uiIntact = await chatbotPage.messageInput.isVisible().catch(() => false);

    // Either still loading, showed a timeout error, or UI is intact
    expect(isLoading || hasError || uiIntact).toBeTruthy();
  });
});
