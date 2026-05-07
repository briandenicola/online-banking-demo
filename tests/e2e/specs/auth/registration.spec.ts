import { test, expect } from '@playwright/test';
import { RegistrationPage } from '../../pages/RegistrationPage';
import { LoginPage } from '../../pages/LoginPage';

test.describe('E2E-201: User Registration Flow', () => {
  let registrationPage: RegistrationPage;
  let loginPage: LoginPage;

  test.beforeEach(async ({ page }) => {
    registrationPage = new RegistrationPage(page);
    loginPage = new LoginPage(page);
    await registrationPage.navigate();
  });

  test('should validate email format', async () => {
    await registrationPage.firstNameInput.fill('Test');
    await registrationPage.lastNameInput.fill('User');
    await registrationPage.emailInput.fill('invalid-email');
    await registrationPage.passwordInput.fill('Password123!');
    await registrationPage.confirmPasswordInput.fill('Password123!');
    await registrationPage.submitButton.click();

    // type="email" triggers HTML5 validation before custom validation runs
    const isInvalid = await registrationPage.page.evaluate(() => {
      const input = document.querySelector('input[type="email"]') as HTMLInputElement;
      return input ? !input.validity.valid : false;
    });
    expect(isInvalid).toBeTruthy();
  });

  test('should validate password minimum length', async () => {
    await registrationPage.firstNameInput.fill('Test');
    await registrationPage.lastNameInput.fill('User');
    await registrationPage.emailInput.fill('test@example.com');
    await registrationPage.passwordInput.fill('short');
    await registrationPage.confirmPasswordInput.fill('short');
    await registrationPage.submitButton.click();

    // Client-side validation shows helperText, not [role="alert"]
    await registrationPage.expectHelperText('at least 8 characters');
  });

  test('should validate password confirmation matches', async () => {
    await registrationPage.firstNameInput.fill('Test');
    await registrationPage.lastNameInput.fill('User');
    await registrationPage.emailInput.fill('test@example.com');
    await registrationPage.passwordInput.fill('Password123!');
    await registrationPage.confirmPasswordInput.fill('DifferentPassword123!');
    await registrationPage.submitButton.click();

    // Client-side validation shows helperText, not [role="alert"]
    await registrationPage.expectHelperText('do not match');
  });

  test('should validate required fields', async () => {
    await registrationPage.submitButton.click();

    await expect(registrationPage.firstNameInput).toBeVisible();
    await expect(registrationPage.lastNameInput).toBeVisible();
    await expect(registrationPage.emailInput).toBeVisible();
  });

  test('should successfully register new user and redirect to login', async () => {
    const timestamp = Date.now();
    const newEmail = `testuser${timestamp}@example.com`;

    await registrationPage.register(
      'Test',
      'User',
      newEmail,
      'Password123!',
      'Password123!'
    );

    await registrationPage.expectNavigatedToLogin();

    const successMessage = registrationPage.page.locator('[role="alert"], .success-message');
    await expect(successMessage).toBeVisible({ timeout: 5_000 });
    await expect(successMessage).toContainText(/registration successful|please sign in/i);
  });

  test('should allow login with newly registered credentials', async () => {
    const timestamp = Date.now();
    const newEmail = `testuser${timestamp}@example.com`;
    const password = 'Password123!';

    await registrationPage.register(
      'Test',
      'User',
      newEmail,
      password,
      password
    );

    await registrationPage.expectNavigatedToLogin();

    await loginPage.login(newEmail, password);
    await loginPage.expectNavigatedToDashboard();
  });

  test('should prevent duplicate email registration', async () => {
    const existingEmail = 'demo@banking-demo.com';

    await registrationPage.register(
      'Test',
      'User',
      existingEmail,
      'Password123!',
      'Password123!'
    );

    await registrationPage.expectError();
  });

  test('should have link to login page', async () => {
    await expect(registrationPage.loginLink).toBeVisible();
    await registrationPage.loginLink.click();
    await registrationPage.page.waitForURL('**/login');
  });
});
