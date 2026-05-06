import { Page, Locator, expect } from '@playwright/test';
import { BasePage } from './BasePage';

export class ChatbotPage extends BasePage {
  readonly path = '/chat';

  readonly chatContainer: Locator;
  readonly messageInput: Locator;
  readonly sendButton: Locator;
  readonly chatMessages: Locator;
  readonly userMessages: Locator;
  readonly botMessages: Locator;
  readonly loadingIndicator: Locator;
  readonly errorMessage: Locator;
  readonly chatToggle: Locator;
  readonly chatWindow: Locator;
  readonly retryButton: Locator;
  readonly newChatButton: Locator;

  constructor(page: Page) {
    super(page);
    this.chatContainer = page.locator(
      '[data-testid="chat-container"], .chat-container, [data-testid="chatbot"], .chatbot-wrapper, main'
    ).first();
    this.messageInput = page.locator(
      'input[placeholder*="message" i], textarea[placeholder*="message" i], input[placeholder*="type" i], textarea[placeholder*="type" i], [data-testid="chat-input"], input[name="message"], textarea[name="message"]'
    ).first();
    this.sendButton = page.locator(
      'button[type="submit"], button[aria-label*="send" i], [data-testid="send-button"], button:has(svg)'
    ).filter({ has: page.locator('svg, :text("Send")') }).first().or(
      page.getByRole('button', { name: /send/i })
    );
    this.chatMessages = page.locator(
      '[data-testid="chat-messages"] > *, .message, .chat-message, [data-testid*="message-"]'
    );
    this.userMessages = page.locator(
      '[data-testid*="user-message"], .user-message, .message-user, [class*="user"]'
    );
    this.botMessages = page.locator(
      '[data-testid*="bot-message"], .bot-message, .message-bot, .assistant-message, [class*="assistant"], [class*="bot"]'
    );
    this.loadingIndicator = page.locator(
      '[data-testid="chat-loading"], .typing-indicator, [role="progressbar"], .MuiCircularProgress-root, [class*="loading"]'
    );
    this.errorMessage = page.locator(
      '[role="alert"], [data-testid="chat-error"], .error-message, .chat-error'
    );
    this.chatToggle = page.locator(
      '[data-testid="chat-toggle"], button[aria-label*="chat" i], .chat-toggle, .chat-fab, .MuiFab-root'
    ).first();
    this.chatWindow = page.locator(
      '[data-testid="chat-window"], .chat-window, .chat-panel, [role="dialog"]:has(input)'
    ).first();
    this.retryButton = page.getByRole('button', { name: /retry|try again/i });
    this.newChatButton = page.getByRole('button', { name: /new chat|clear|reset/i });
  }

  async expectLoaded(): Promise<void> {
    await expect(this.chatContainer.or(this.chatWindow)).toBeVisible({ timeout: 10_000 });
  }

  async openChat(): Promise<void> {
    const isWindowVisible = await this.chatWindow.isVisible().catch(() => false);
    const isContainerVisible = await this.chatContainer.isVisible().catch(() => false);
    if (!isWindowVisible && !isContainerVisible) {
      const toggleVisible = await this.chatToggle.isVisible().catch(() => false);
      if (toggleVisible) {
        await this.chatToggle.click();
        await expect(this.chatWindow.or(this.chatContainer)).toBeVisible({ timeout: 5_000 });
      }
    }
  }

  async sendMessage(message: string): Promise<void> {
    await this.messageInput.fill(message);
    // Try clicking send, fallback to Enter key
    const sendVisible = await this.sendButton.isVisible().catch(() => false);
    if (sendVisible) {
      await this.sendButton.click();
    } else {
      await this.messageInput.press('Enter');
    }
  }

  async waitForResponse(timeout = 30_000): Promise<void> {
    // Wait for loading indicator to appear and disappear, or for a new bot message
    const loadingAppeared = await this.loadingIndicator.isVisible().catch(() => false);
    if (loadingAppeared) {
      await expect(this.loadingIndicator).toBeHidden({ timeout });
    } else {
      await this.page.waitForTimeout(2000);
    }
  }

  async sendAndWaitForResponse(message: string, timeout = 30_000): Promise<void> {
    const messageCountBefore = await this.botMessages.count();
    await this.sendMessage(message);
    // Wait for a new bot message to appear
    await expect(this.botMessages).toHaveCount(messageCountBefore + 1, { timeout }).catch(async () => {
      // Fallback: just wait for loading to finish
      await this.waitForResponse(timeout);
    });
  }

  async getMessageCount(): Promise<number> {
    return this.chatMessages.count();
  }

  async getBotMessageCount(): Promise<number> {
    return this.botMessages.count();
  }

  async getLastBotMessage(): Promise<string> {
    const count = await this.botMessages.count();
    if (count === 0) return '';
    return (await this.botMessages.nth(count - 1).textContent()) || '';
  }

  async getLastUserMessage(): Promise<string> {
    const count = await this.userMessages.count();
    if (count === 0) return '';
    return (await this.userMessages.nth(count - 1).textContent()) || '';
  }

  async hasErrorMessage(): Promise<boolean> {
    return this.errorMessage.isVisible().catch(() => false);
  }

  async startNewChat(): Promise<void> {
    const hasNewChat = await this.newChatButton.isVisible().catch(() => false);
    if (hasNewChat) {
      await this.newChatButton.click();
      await this.page.waitForTimeout(500);
    }
  }

  async expectResponseContains(text: string): Promise<void> {
    const lastMessage = await this.getLastBotMessage();
    expect(lastMessage.toLowerCase()).toContain(text.toLowerCase());
  }
}
