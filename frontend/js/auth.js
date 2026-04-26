/**
 * GREEN App — Authentication Page Logic
 * Handles login form and register form submission,
 * validation, error display, and redirect after success.
 *
 * Works on both: index.html (login) and register.html (register).
 */

/* ============================================================
   PAGE DETECTION
   Check which page we're on and initialise accordingly.
   ============================================================ */
document.addEventListener('DOMContentLoaded', () => {
  // If already logged in, skip auth pages
  // (Disabled during development to allow easy testing)
  // Auth.redirectIfLoggedIn();

  const loginForm    = document.getElementById('loginForm');
  const registerForm = document.getElementById('registerForm');

  if (loginForm)    initLoginPage();
  if (registerForm) initRegisterPage();
});


/* ============================================================
   LOGIN PAGE
   ============================================================ */

function initLoginPage() {
  const form      = document.getElementById('loginForm');
  const submitBtn = document.getElementById('loginSubmitBtn');

  // ---- Password visibility toggle
  const togglePwdBtn = document.getElementById('togglePassword');
  if (togglePwdBtn) {
    togglePwdBtn.addEventListener('click', () => {
      togglePasswordVisibility('password', 'togglePassword');
    });
  }

  // ---- Clear field errors on input
  ['identifier', 'password'].forEach(id => {
    const input = document.getElementById(id);
    if (input) {
      input.addEventListener('input', () => {
        clearFieldError(id);
        hideAlert('loginAlert');
      });
    }
  });

  // ---- Form submission
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    hideAlert('loginAlert');
    clearAllErrors('loginForm');

    const identifier = document.getElementById('identifier').value.trim();
    const password   = document.getElementById('password').value;

    // Client-side validation
    let isValid = true;

    if (!identifier) {
      showFieldError('identifier', 'Please enter your phone number or email.');
      isValid = false;
    }
    if (!password) {
      showFieldError('password', 'Please enter your password.');
      isValid = false;
    }
    if (!isValid) return;

    // Show loading state
    setButtonLoading('loginSubmitBtn', true);

    // API call
    const { data, error } = await API.auth.login({ identifier, password });

    setButtonLoading('loginSubmitBtn', false);

    if (error) {
      showAlert('loginAlert', error, 'error');
      return;
    }

    // Save session
    Auth.save(data.access_token, data.user);

    // Show brief success feedback then redirect
    showAlert('loginAlert', 'Welcome back! Redirecting...', 'success');
    setTimeout(() => {
      window.location.replace('/dashboard');
    }, 800);
  });
}


/* ============================================================
   REGISTER PAGE
   ============================================================ */

function initRegisterPage() {
  const form = document.getElementById('registerForm');

  // ---- Password visibility toggles
  const togglePwd = document.getElementById('togglePassword');
  if (togglePwd) {
    togglePwd.addEventListener('click', () =>
      togglePasswordVisibility('password', 'togglePassword')
    );
  }

  const toggleConfirm = document.getElementById('toggleConfirmPassword');
  if (toggleConfirm) {
    toggleConfirm.addEventListener('click', () =>
      togglePasswordVisibility('confirm_password', 'toggleConfirmPassword')
    );
  }

  // ---- Live password strength indicator
  const pwdInput = document.getElementById('password');
  if (pwdInput) {
    pwdInput.addEventListener('input', () => {
      updatePasswordStrength(pwdInput.value, 'passwordStrengthBars', 'passwordStrengthLabel');
      clearFieldError('password');
    });
  }

  // ---- Clear field errors on input
  ['first_name', 'last_name', 'phone', 'email', 'password', 'confirm_password'].forEach(id => {
    const input = document.getElementById(id);
    if (input) {
      input.addEventListener('input', () => {
        clearFieldError(id);
        hideAlert('registerAlert');
      });
    }
  });

  // ---- Form submission
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    hideAlert('registerAlert');
    clearAllErrors('registerForm');

    // Collect values
    const first_name      = document.getElementById('first_name').value.trim();
    const last_name       = document.getElementById('last_name').value.trim();
    const phone           = document.getElementById('phone').value.trim();
    const email           = document.getElementById('email').value.trim();
    const password        = document.getElementById('password').value;
    const confirmPassword = document.getElementById('confirm_password').value;
    const company_name    = document.getElementById('company_name')?.value.trim();
    const region          = document.getElementById('region')?.value;

    // ---- Client-side validation
    let isValid = true;

    if (!first_name) {
      showFieldError('first_name', 'First name is required.');
      isValid = false;
    }
    if (!last_name) {
      showFieldError('last_name', 'Last name is required.');
      isValid = false;
    }
    if (!phone) {
      showFieldError('phone', 'Phone number is required.');
      isValid = false;
    } else if (!/^\+?[0-9\s\-]{8,15}$/.test(phone)) {
      showFieldError('phone', 'Please enter a valid phone number.');
      isValid = false;
    }
    if (email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
      showFieldError('email', 'Please enter a valid email address.');
      isValid = false;
    }
    if (!password) {
      showFieldError('password', 'Password is required.');
      isValid = false;
    } else if (password.length < 6) {
      showFieldError('password', 'Password must be at least 6 characters.');
      isValid = false;
    }
    if (!confirmPassword) {
      showFieldError('confirm_password', 'Please confirm your password.');
      isValid = false;
    } else if (password !== confirmPassword) {
      showFieldError('confirm_password', 'Passwords do not match.');
      isValid = false;
    }

    if (!isValid) return;

    // ---- Build request payload (omit empty optional fields)
    const payload = { first_name, last_name, phone, password };
    if (email)        payload.email        = email;
    if (company_name) payload.company_name = company_name;
    if (region)       payload.region       = region;

    // ---- API call
    setButtonLoading('registerSubmitBtn', true);

    const { data, error } = await API.auth.register(payload);

    setButtonLoading('registerSubmitBtn', false);

    if (error) {
      showAlert('registerAlert', error, 'error');
      return;
    }

    // Save session and redirect
    Auth.save(data.access_token, data.user);
    showAlert('registerAlert', 'Account created! Redirecting to your dashboard...', 'success');
    setTimeout(() => {
      window.location.replace('/dashboard');
    }, 900);
  });
}
