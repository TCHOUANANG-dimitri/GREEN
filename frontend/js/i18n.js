/**
 * GREEN App — i18n (Internationalization) Module
 * Handles language switching between English (default) and French
 * Stores preference in localStorage
 */

const i18n = {
  // Current language
  currentLang: 'en',

  // Translation dictionary loaded from translations.json
  translations: {},

  /**
   * Initialize i18n system
   * Load translations and set current language from localStorage
   */
  async init() {
    try {
      // Load translations from JSON file
      const response = await fetch('/js/translations.json');
      this.translations = await response.json();

      // Get saved language or default to 'en'
      const saved = localStorage.getItem('green_language') || 'en';
      this.setLanguage(saved);
      
      return true;
    } catch (e) {
      console.error('[i18n] Failed to load translations:', e);
      this.currentLang = 'en';
      return false;
    }
  },

  /**
   * Set the current language and update the DOM
   * @param {string} lang - Language code ('en' or 'fr')
   */
  setLanguage(lang) {
    if (lang !== 'en' && lang !== 'fr') {
      console.warn(`[i18n] Invalid language: ${lang}, defaulting to 'en'`);
      lang = 'en';
    }

    this.currentLang = lang;
    localStorage.setItem('green_language', lang);
    document.documentElement.lang = lang;

    // Update all text nodes with data-i18n attributes
    this._updateDOM();

    // Update navigation labels if Layout is loaded
    if (typeof Layout !== 'undefined' && Layout.updateNavLabels) {
      Layout.updateNavLabels();
    }

    // Trigger custom event for other scripts to listen
    window.dispatchEvent(new CustomEvent('languageChanged', { detail: { lang } }));
  },

  /**
   * Get translated text for a key
   * @param {string} key - Translation key (e.g., 'auth.sign_in')
   * @param {object} params - Optional parameters for substitution
   * @returns {string} Translated text or key if not found
   */
  t(key, params = {}) {
    const keys = key.split('.');
    let value = this.translations[this.currentLang];

    // Navigate nested object
    for (const k of keys) {
      if (value && typeof value === 'object' && k in value) {
        value = value[k];
      } else {
        console.warn(`[i18n] Missing translation key: ${key}`);
        return key;
      }
    }

    // Replace parameters if provided
    if (typeof value === 'string' && Object.keys(params).length > 0) {
      Object.entries(params).forEach(([key, val]) => {
        value = value.replace(`{{${key}}}`, val);
      });
    }

    return value || key;
  },

  /**
   * Update DOM elements with i18n attributes
   * Looks for data-i18n attributes and updates text content
   */
  _updateDOM() {
    // Update text content
    document.querySelectorAll('[data-i18n]').forEach((el) => {
      const key = el.getAttribute('data-i18n');
      const translated = this.t(key);
      
      // If element has child nodes with text, update the direct text
      if (el.childNodes.length === 0) {
        el.textContent = translated;
      } else {
        // For elements with children, only update the first text node
        let found = false;
        for (const node of el.childNodes) {
          if (node.nodeType === Node.TEXT_NODE && node.textContent.trim()) {
            node.textContent = translated;
            found = true;
            break;
          }
        }
        if (!found) {
          el.textContent = translated;
        }
      }
    });

    // Update placeholders
    document.querySelectorAll('[data-i18n-placeholder]').forEach((el) => {
      const key = el.getAttribute('data-i18n-placeholder');
      el.placeholder = this.t(key);
    });

    // Update titles (for tooltips, alt text, etc.)
    document.querySelectorAll('[data-i18n-title]').forEach((el) => {
      const key = el.getAttribute('data-i18n-title');
      el.title = this.t(key);
    });

    // Update aria-labels
    document.querySelectorAll('[data-i18n-aria]').forEach((el) => {
      const key = el.getAttribute('data-i18n-aria');
      el.setAttribute('aria-label', this.t(key));
    });
  },

  /**
   * Get current language
   */
  getLang() {
    return this.currentLang;
  },

  /**
   * Check if current language is English
   */
  isEnglish() {
    return this.currentLang === 'en';
  },

  /**
   * Check if current language is French
   */
  isFrench() {
    return this.currentLang === 'fr';
  },
};

// Auto-initialize when DOM is ready and i18n.js is loaded
document.addEventListener('DOMContentLoaded', async () => {
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => i18n.init());
  } else {
    await i18n.init();
  }
});
