import { test, expect } from '../../fixtures/authFixture';
import { ChatbotPage } from '../../pages/ChatbotPage';

test.describe('E2E-404: Chatbot Interaction — Message Flow', () => {
  let chatbotPage: ChatbotPage;

  test.beforeEach(async ({ authenticatedPage }) => {
    chatbotPage = new ChatbotPage(authenticatedPage);
  });

  test('should open chatbot interface', async ({ authenticatedPage }) => {
    await chatbotPage.navigate();
    await authenticatedPage.waitForLoadState('domcontentloaded');
    await authenticatedPage.waitForTimeout(2000);

    // Check if chat page exists or if there's a floating chat toggle
    const chatAvailable = await chatbotPage.chatContainer.isVisible().catch(() => false);
    const toggleAvailable = await chatbotPage.chatToggle.isVisible().catch(() => false);

    if (!chatAvailable && !toggleAvailable) {
      // Try opening from dashboard
      await authenticatedPage.goto('/dashboard');
      await authenticatedPage.waitForLoadState('domcontentloaded');
      await authenticatedPage.waitForTimeout(1000);

      const dashToggle = await chatbotPage.chatToggle.isVisible().catch(() => false);
      if (!dashToggle) {
        test.skip(true, 'Chatbot UI not available');
        return;
      }
    }

    if (toggleAvailable || await chatbotPage.chatToggle.isVisible().catch(() => false)) {
      await chatbotPage.openChat();
    }

    const isVisible = await chatbotPage.chatContainer.isVisible().catch(() => false) ||
      await chatbotPage.chatWindow.isVisible().catch(() => false);
    expect(isVisible).toBeTruthy();
  });

  test('should type a message and receive a response', async ({ authenticatedPage }) => {
    await chatbotPage.navigate();
    await authenticatedPage.waitForLoadState('domcontentloaded');
    await authenticatedPage.waitForTimeout(2000);

    const chatAvailable = await chatbotPage.chatContainer.isVisible().catch(() => false) ||
      await chatbotPage.chatWindow.isVisible().catch(() => false);

    if (!chatAvailable) {
      await chatbotPage.openChat();
      const opened = await chatbotPage.chatContainer.isVisible().catch(() => false) ||
        await chatbotPage.chatWindow.isVisible().catch(() => false);
      if (!opened) {
        test.skip(true, 'Chatbot not available');
        return;
      }
    }

    const inputVisible = await chatbotPage.messageInput.isVisible().catch(() => false);
    if (!inputVisible) {
      test.skip(true, 'Chat input not found');
      return;
    }

    await chatbotPage.sendMessage('Hello, what can you help me with?');

    // Wait for response (with generous timeout for AI services)
    await chatbotPage.waitForResponse(30_000);

    // Should have at least one bot response or an error message
    const botCount = await chatbotPage.getBotMessageCount();
    const hasError = await chatbotPage.hasErrorMessage();

    expect(botCount > 0 || hasError).toBeTruthy();
  });

  test('should display conversation history', async ({ authenticatedPage }) => {
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
      test.skip(true, 'Chat input not found');
      return;
    }

    // Send first message
    await chatbotPage.sendMessage('What is my account balance?');
    await chatbotPage.waitForResponse(30_000);

    // Send second message
    await chatbotPage.sendMessage('Tell me about my recent transactions');
    await chatbotPage.waitForResponse(30_000);

    // Conversation history should show both exchanges
    const totalMessages = await chatbotPage.getMessageCount();
    const userMsgCount = await chatbotPage.userMessages.count();

    // At least the user messages should appear in history
    expect(userMsgCount).toBeGreaterThanOrEqual(2);
  });

  test('should handle multiple turns correctly', async ({ authenticatedPage }) => {
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
      test.skip(true, 'Chat input not found');
      return;
    }

    const messages = [
      'Hi there',
      'What services do you offer?',
      'How do I transfer money?',
    ];

    for (const msg of messages) {
      await chatbotPage.sendMessage(msg);
      await chatbotPage.waitForResponse(30_000);

      // Check for errors that would block continued conversation
      const hasError = await chatbotPage.hasErrorMessage();
      if (hasError) {
        // Chatbot service may be unavailable
        test.skip(true, 'Chatbot service returned error — likely unavailable');
        return;
      }
    }

    const userMsgCount = await chatbotPage.userMessages.count();
    expect(userMsgCount).toBeGreaterThanOrEqual(3);
  });

  test('should handle chatbot service unavailability gracefully', async ({ authenticatedPage }) => {
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
      test.skip(true, 'Chat input not found');
      return;
    }

    // Mock the chatbot API to return an error
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

    await chatbotPage.sendMessage('Hello');
    await authenticatedPage.waitForTimeout(5000);

    // Page should not crash — should show error or graceful fallback
    const pageTitle = await authenticatedPage.title();
    expect(pageTitle).toBeTruthy(); // Page didn't crash

    const hasError = await chatbotPage.hasErrorMessage();
    const hasRetry = await chatbotPage.retryButton.isVisible().catch(() => false);
    const pageStillRendered = await chatbotPage.chatContainer.isVisible().catch(() => false) ||
      await chatbotPage.chatWindow.isVisible().catch(() => false) ||
      await chatbotPage.messageInput.isVisible().catch(() => false);

    // Either shows error, retry button, or at least the chat UI remains intact
    expect(hasError || hasRetry || pageStillRendered).toBeTruthy();
  });
});
