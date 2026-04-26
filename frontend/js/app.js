/**
 * GREEN App — App-Wide Logic
 * Authentication guard, user session refresh, and shared
 * behaviours used across all inner (post-login) pages.
 *
 * Include this AFTER utils.js, api.js, and layout.js.
 * Layout.init() must be called from each page individually.
 */

/* ============================================================
   APP BOOTSTRAP
   Run as soon as DOMContentLoaded fires on any inner page.
   ============================================================ */
document.addEventListener('DOMContentLoaded', () => {
  App.boot();
});


/* ============================================================
   APP OBJECT
   ============================================================ */
const App = {

  /**
   * Boot sequence for every protected page.
   * 1. Verify the user is logged in (redirect if not).
   * 2. Optionally refresh user data from the server.
   */
  async boot() {
    // ---- Auth guard: redirect to login if no token ----
    if (!Auth.isLoggedIn()) {
      window.location.replace('/');
      return;
    }

    // ---- Refresh user profile from server in background ----
    // This ensures stale cached data is updated, but doesn't
    // block the page from rendering (Layout.init already ran).
    this._refreshUser();
  },

  /**
   * Fetch the latest user profile from the server and update
   * the local cache + sidebar/header display.
   */
  async _refreshUser() {
    try {
      const { data, error } = await API.auth.me();
      if (data && !error) {
        Auth.updateUser(data);
        if (typeof Layout !== 'undefined') {
          Layout.refreshUser();
        }
      } else if (error && (error.includes('401') || error.includes('Invalid'))) {
        // Token expired → force logout
        this.logout();
      }
    } catch (e) {
      // Silently fail — the page still works with cached user data
      console.warn('[GREEN App] Could not refresh user profile:', e.message);
    }
  },

  /**
   * Sign the user out: clear session and redirect to login.
   * Callable from the profile page, settings, or any page.
   */
  logout() {
    Auth.clear();
    window.location.replace('/');
  },

  /**
   * Show a global toast notification (non-blocking message).
   * @param {string} message   - Text to display.
   * @param {'success'|'error'|'info'|'warning'} type
   * @param {number} duration  - Auto-dismiss delay in ms (0 = no auto-dismiss).
   */
  toast(message, type = 'info', duration = 4000) {
    // Create toast container if it doesn't exist
    let container = document.getElementById('toastContainer');
    if (!container) {
      container = document.createElement('div');
      container.id = 'toastContainer';
      container.style.cssText = `
        position: fixed;
        bottom: 24px;
        right: 24px;
        z-index: 9999;
        display: flex;
        flex-direction: column;
        gap: 8px;
        pointer-events: none;
      `;
      document.body.appendChild(container);
    }

    // Color map per type
    const colors = {
      success: { bg: 'var(--color-success-bg)',  border: 'var(--color-success-border)', text: '#166534', icon: '✓' },
      error:   { bg: 'var(--color-error-bg)',    border: 'var(--color-error-border)',   text: '#991B1B', icon: '✕' },
      warning: { bg: 'var(--color-warning-bg)',  border: 'var(--color-warning-border)', text: '#92400E', icon: '!' },
      info:    { bg: 'var(--color-info-bg)',     border: 'var(--color-info-border)',    text: '#1E40AF', icon: 'i' },
    };
    const c = colors[type] || colors.info;

    // Dark mode override
    const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
    const darkOverrides = {
      success: { bg: 'rgba(34,197,94,0.12)',   border: 'rgba(34,197,94,0.3)',  text: '#86EFAC' },
      error:   { bg: 'rgba(239,68,68,0.12)',   border: 'rgba(239,68,68,0.3)', text: '#FCA5A5' },
      warning: { bg: 'rgba(245,158,11,0.12)',  border: 'rgba(245,158,11,0.3)',text: '#FCD34D' },
      info:    { bg: 'rgba(59,130,246,0.12)',  border: 'rgba(59,130,246,0.3)',text: '#93C5FD' },
    };
    if (isDark) Object.assign(c, darkOverrides[type] || {});

    // Build toast element
    const toast = document.createElement('div');
    toast.style.cssText = `
      display: flex;
      align-items: center;
      gap: 10px;
      padding: 12px 16px;
      background: ${c.bg};
      border: 1px solid ${c.border};
      border-radius: 10px;
      font-size: 0.875rem;
      font-weight: 500;
      color: ${c.text};
      box-shadow: 0 4px 12px rgba(0,0,0,0.12);
      pointer-events: all;
      min-width: 240px;
      max-width: 360px;
      animation: slideUp 0.3s cubic-bezier(0.34,1.56,0.64,1);
      font-family: var(--font-sans, Inter, sans-serif);
    `;
    toast.innerHTML = `
      <span style="font-weight:700;font-size:0.8rem;width:18px;text-align:center;">${c.icon}</span>
      <span style="flex:1;">${message}</span>
    `;
    container.appendChild(toast);

    // Auto-dismiss
    if (duration > 0) {
      setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transform = 'translateX(20px)';
        toast.style.transition = 'opacity 300ms, transform 300ms';
        setTimeout(() => toast.remove(), 300);
      }, duration);
    }
  },

  /**
   * Confirm dialog before destructive actions.
   * Returns true if the user confirms, false otherwise.
   * @param {string} message
   */
  confirm(message) {
    return window.confirm(message);
  }
};
