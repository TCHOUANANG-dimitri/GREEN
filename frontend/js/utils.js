/**
 * GREEN App — Utility Functions
 * Shared helpers used across all pages.
 * Imported before api.js and page-specific JS files.
 */

/* ============================================================
   THEME MANAGEMENT
   The theme (dark/light) is stored in localStorage and applied
   by setting data-theme="dark" on the <html> element.
   Theme toggling happens ONLY in the Settings page.
   On all other pages, we just restore the saved preference.
   ============================================================ */

const ThemeManager = {
  /** Key used in localStorage to persist the theme choice. */
  STORAGE_KEY: 'green_theme',

  /**
   * Apply the saved theme (or system default) on page load.
   * Call this at the top of every page's <script> to avoid flash.
   */
  init() {
    const saved = localStorage.getItem(this.STORAGE_KEY);
    if (saved) {
      document.documentElement.setAttribute('data-theme', saved);
    } else {
      // Respect the OS-level preference if no user choice saved
      const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
      const theme = prefersDark ? 'dark' : 'light';
      document.documentElement.setAttribute('data-theme', theme);
    }
  },

  /** Returns the current active theme: 'dark' or 'light'. */
  get() {
    return document.documentElement.getAttribute('data-theme') || 'light';
  },

  /** Switch between dark and light. Called from Settings page. */
  toggle() {
    const current = this.get();
    const next = current === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', next);
    localStorage.setItem(this.STORAGE_KEY, next);
    return next;
  },

  /** Set a specific theme explicitly. */
  set(theme) {
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem(this.STORAGE_KEY, theme);
  }
};

// Apply theme immediately (before DOM renders to prevent flash)
ThemeManager.init();


/* ============================================================
   LANGUAGE MANAGEMENT
   Stores user's preferred language. Used by i18n system.
   Language switching is done in Settings page only.
   ============================================================ */
const LangManager = {
  STORAGE_KEY: 'green_lang',
  SUPPORTED: ['en', 'fr'],

  init() {
    const saved = localStorage.getItem(this.STORAGE_KEY);
    if (!saved || !this.SUPPORTED.includes(saved)) {
      localStorage.setItem(this.STORAGE_KEY, 'en');
    }
  },

  get() {
    return localStorage.getItem(this.STORAGE_KEY) || 'en';
  },

  set(lang) {
    if (this.SUPPORTED.includes(lang)) {
      localStorage.setItem(this.STORAGE_KEY, lang);
    }
  }
};
LangManager.init();


/* ============================================================
   TOKEN / SESSION MANAGEMENT
   JWT stored in localStorage under 'green_token'.
   ============================================================ */
const Auth = {
  TOKEN_KEY: 'green_token',
  USER_KEY:  'green_user',

  /** Save token and user profile after login/register. */
  save(token, user) {
    localStorage.setItem(this.TOKEN_KEY, token);
    localStorage.setItem(this.USER_KEY, JSON.stringify(user));
  },

  /** Retrieve the JWT token string. */
  getToken() {
    return localStorage.getItem(this.TOKEN_KEY);
  },

  /** Retrieve the cached user object. */
  getUser() {
    try {
      return JSON.parse(localStorage.getItem(this.USER_KEY));
    } catch {
      return null;
    }
  },

  /** Update just the cached user object (after profile edit). */
  updateUser(user) {
    localStorage.setItem(this.USER_KEY, JSON.stringify(user));
  },

  /** Remove token and user — used on logout or account deletion. */
  clear() {
    localStorage.removeItem(this.TOKEN_KEY);
    localStorage.removeItem(this.USER_KEY);
  },

  /** Returns true if a token exists (basic check). */
  isLoggedIn() {
    return !!this.getToken();
  },

  /**
   * Redirect to login if the user is not authenticated.
   * Call at the top of every protected page.
   */
  requireAuth() {
    if (!this.isLoggedIn()) {
      window.location.replace('/');
    }
  },

  /**
   * Redirect away from auth pages if already logged in.
   * Call at the top of login/register pages.
   */
  redirectIfLoggedIn() {
    if (this.isLoggedIn()) {
      window.location.replace('/dashboard');
    }
  }
};


/* ============================================================
   FORM UTILITIES
   ============================================================ */

/**
 * Show an error message under a specific input field.
 * @param {string} fieldId - The id of the input element.
 * @param {string} message - Error message to display.
 */
function showFieldError(fieldId, message) {
  const input = document.getElementById(fieldId);
  const errorEl = document.getElementById(fieldId + '_error');

  if (input) {
    input.classList.add('error');
  }
  if (errorEl) {
    errorEl.textContent = message;
    errorEl.classList.add('visible');
  }
}

/**
 * Clear error state from an input field.
 * @param {string} fieldId - The id of the input element.
 */
function clearFieldError(fieldId) {
  const input = document.getElementById(fieldId);
  const errorEl = document.getElementById(fieldId + '_error');

  if (input) input.classList.remove('error');
  if (errorEl) {
    errorEl.textContent = '';
    errorEl.classList.remove('visible');
  }
}

/** Clear all field errors in a form. */
function clearAllErrors(formId) {
  const form = document.getElementById(formId);
  if (!form) return;

  form.querySelectorAll('.form-input.error').forEach(el => el.classList.remove('error'));
  form.querySelectorAll('.field-error.visible').forEach(el => {
    el.textContent = '';
    el.classList.remove('visible');
  });
}

/**
 * Show a global alert message (success or error) above the form.
 * @param {string} alertId - The id of the alert element.
 * @param {string} message - Text to show.
 * @param {'error'|'success'} type - Alert style.
 */
function showAlert(alertId, message, type = 'error') {
  const el = document.getElementById(alertId);
  if (!el) return;

  el.textContent = message;
  el.className = `alert alert-${type}`;
  el.style.display = 'flex';
}

/** Hide a global alert element. */
function hideAlert(alertId) {
  const el = document.getElementById(alertId);
  if (el) el.style.display = 'none';
}

/**
 * Set a button to loading state (shows spinner, disables button).
 * @param {string} btnId - The id of the button element.
 * @param {boolean} loading - true = loading, false = normal.
 */
function setButtonLoading(btnId, loading) {
  const btn = document.getElementById(btnId);
  if (!btn) return;

  if (loading) {
    btn.classList.add('loading');
    btn.disabled = true;
  } else {
    btn.classList.remove('loading');
    btn.disabled = false;
  }
}

/**
 * Toggle password field visibility (show/hide text).
 * @param {string} inputId  - The password input id.
 * @param {string} toggleId - The eye button id.
 */
function togglePasswordVisibility(inputId, toggleId) {
  const input  = document.getElementById(inputId);
  const toggle = document.getElementById(toggleId);
  if (!input || !toggle) return;

  const isHidden = input.type === 'password';
  input.type = isHidden ? 'text' : 'password';

  // Swap the icon
  toggle.querySelector('.icon-eye-open').style.display  = isHidden ? 'none' : 'block';
  toggle.querySelector('.icon-eye-close').style.display = isHidden ? 'block' : 'none';
}


/* ============================================================
   PASSWORD STRENGTH
   ============================================================ */

/**
 * Evaluate password strength and update the visual bar.
 * Strength levels: 0 = empty, 1 = weak, 2 = medium, 3 = strong.
 * @param {string} password
 * @param {string} barContainerId - Id of the .password-strength container.
 * @param {string} labelId        - Id of the .strength-label element.
 */
function updatePasswordStrength(password, barContainerId, labelId) {
  const bars = document.querySelectorAll(`#${barContainerId} .strength-bar`);
  const label = document.getElementById(labelId);
  if (!bars.length) return;

  let score = 0;
  if (password.length >= 6)  score++;
  if (password.length >= 10) score++;
  if (/[A-Z]/.test(password) && /[0-9!@#$%^&*]/.test(password)) score++;

  const classes = ['', 'weak', 'medium', 'strong'];
  const labels  = ['', 'Weak', 'Moderate', 'Strong'];

  bars.forEach((bar, i) => {
    bar.className = 'strength-bar';
    if (i < score && score > 0) {
      bar.classList.add(classes[score]);
    }
  });

  if (label) {
    label.textContent = password.length > 0 ? `Strength: ${labels[score]}` : '';
    label.style.color = score === 1 ? 'var(--color-error)'
                      : score === 2 ? 'var(--color-warning)'
                      : score === 3 ? 'var(--color-success)'
                      : 'var(--text-muted)';
  }
}


/* ============================================================
   MISCELLANEOUS HELPERS
   ============================================================ */

/**
 * Get the user's initials from first/last name (for avatar fallback).
 * @param {string} firstName
 * @param {string} lastName
 * @returns {string} e.g. "TD"
 */
function getInitials(firstName, lastName) {
  const f = (firstName || '').trim()[0] || '';
  const l = (lastName  || '').trim()[0] || '';
  return (f + l).toUpperCase();
}

/**
 * Format a date string for display (e.g. "April 10, 2026").
 * @param {string|Date} dateInput
 * @returns {string}
 */
function formatDate(dateInput) {
  const date = new Date(dateInput);
  return date.toLocaleDateString('en-US', {
    year: 'numeric', month: 'long', day: 'numeric'
  });
}

/**
 * Debounce a function (limit how often it fires).
 * @param {Function} fn
 * @param {number} delay - milliseconds
 */
function debounce(fn, delay = 300) {
  let timer;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), delay);
  };
}
