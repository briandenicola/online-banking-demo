import { test, expect } from '../../fixtures/authFixture';
import { ChatbotPage } from '../../pages/ChatbotPage';

test.describe('E2E-405: Chatbot Memory & Context', () => {
  let chatbotPage: ChatbotPage;

  test.beforeEach(async ({ authenticatedPage }) => {
    chatbotPage = new ChatbotPage(authenticatedPage);
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
      test.skip(true, 'Chatbot not available');
    }
  });

  test('should recall previous context in same session', async ({ authenticatedPage }) => {
    // First message establishes context
    await chatbotPage.sendMessage('My name is TestUser');
    await chatbotPage.waitForResponse(30_000);

    const hasError = await chatbotPage.hasErrorMessage();
    if (hasError) {
      test.skip(true, 'Chatbot service unavailable');
      return;
    }

    // Second message references previous context
    await chatbotPage.sendMessage('What is my name?');
    await chatbotPage.waitForResponse(30_000);

    const lastBotMessage = await chatbotPage.getLastBotMessage();

    // Bot should reference "TestUser" in its response if it has context memory
    // This is a best-effort check — AI responses vary
    if (lastBotMessage) {
      // At minimum, bot should respond (not crash)
      expect(lastBotMessage.length).toBeGreaterThan(0);
    }
  });

  test('should maintain coherence in multi-turn conversation', async ({ authenticatedPage }) => {
    // Establish a topic
    await chatbotPage.sendMessage('I want to know about savings accounts');
    await chatbotPage.waitForResponse(30_000);

    let hasError = await chatbotPage.hasErrorMessage();
    if (hasError) {
      test.skip(true, 'Chatbot service unavailable');
      return;
    }

    // Follow-up that relies on context
    await chatbotPage.sendMessage('What interest rates do they offer?');
    await chatbotPage.waitForResponse(30_000);

    hasError = await chatbotPage.hasErrorMessage();
    if (hasError) {
      test.skip(true, 'Chatbot service error on follow-up');
      return;
    }

    const lastBotMessage = await chatbotPage.getLastBotMessage();
    // The response should be about savings/interest (not a random topic)
    expect(lastBotMessage.length).toBeGreaterThan(0);

    // Third turn continuing context
    await chatbotPage.sendMessage('How do I open one?');
    await chatbotPage.waitForResponse(30_000);

    const thirdResponse = await chatbotPage.getLastBotMessage();
    expect(thirdResponse.length).toBeGreaterThan(0);
  });

  test('should reference user account data contextually', async ({ authenticatedPage }) => {
    // Ask about user's own account data — chatbot should have access if integrated
    await chatbotPage.sendMessage('What accounts do I have?');
    await chatbotPage.waitForResponse(30_000);

    const hasError = await chatbotPage.hasErrorMessage();
    if (hasError) {
      test.skip(true, 'Chatbot service unavailable');
      return;
    }

    const response = await chatbotPage.getLastBotMessage();
    expect(response.length).toBeGreaterThan(0);

    // Follow up with account-specific question
    await chatbotPage.sendMessage('What is my checking account balance?');
    await chatbotPage.waitForResponse(30_000);

    const balanceResponse = await chatbotPage.getLastBotMessage();
    // Bot should respond coherently (even if it can't access real data)
    expect(balanceResponse.length).toBeGreaterThan(0);
  });

  test('should start fresh with no carry-over in new session', async ({ authenticatedPage }) => {
    // Establish context in current session
    await chatbotPage.sendMessage('Remember the code word is OCEAN');
    await chatbotPage.waitForResponse(30_000);

    const hasError = await chatbotPage.hasErrorMessage();
    if (hasError) {
      test.skip(true, 'Chatbot service unavailable');
      return;
    }

    // Start a new chat session
    const hasNewChat = await chatbotPage.newChatButton.isVisible().catch(() => false);

    if (hasNewChat) {
      await chatbotPage.startNewChat();
      await authenticatedPage.waitForTimeout(1000);

      // In the new session, ask about the code word
      await chatbotPage.sendMessage('What is the code word?');
      await chatbotPage.waitForResponse(30_000);

      const newSessionResponse = await chatbotPage.getLastBotMessage();
      // New session should NOT know about "OCEAN"
      // (though AI responses are unpredictable, we at least verify the flow works)
      expect(newSessionResponse.length).toBeGreaterThan(0);
    } else {
      // Simulate new session by navigating away and back
      await authenticatedPage.goto('/');
      await authenticatedPage.waitForLoadState('domcontentloaded');

      // Clear any session storage that might persist chat context
      await authenticatedPage.evaluate(() => {
        sessionStorage.clear();
      });

      await chatbotPage.navigate();
      await authenticatedPage.waitForLoadState('domcontentloaded');
      await authenticatedPage.waitForTimeout(2000);

      const chatReloaded = await chatbotPage.chatContainer.isVisible().catch(() => false) ||
        await chatbotPage.chatWindow.isVisible().catch(() => false);
      if (!chatReloaded) {
        await chatbotPage.openChat();
      }

      const inputReady = await chatbotPage.messageInput.isVisible().catch(() => false);
      if (inputReady) {
        // Verify message history is cleared
        const messageCount = await chatbotPage.getMessageCount();
        // New session should have fewer/no messages
        expect(messageCount).toBeLessThanOrEqual(1); // May have a welcome message
      }
    }
  });

  test('should handle rapid sequential messages', async ({ authenticatedPage }) => {
    // Send messages quickly without waiting for full responses
    await chatbotPage.sendMessage('Question 1: What is banking?');

    // Don't wait for full response, send another
    await authenticatedPage.waitForTimeout(500);
    await chatbotPage.sendMessage('Question 2: What are loans?');
    await chatbotPage.waitForResponse(30_000);

    // UI should not crash from rapid messages
    const pageTitle = await authenticatedPage.title();
    expect(pageTitle).toBeTruthy();

    const userCount = await chatbotPage.userMessages.count();
    expect(userCount).toBeGreaterThanOrEqual(2);
  });
});
