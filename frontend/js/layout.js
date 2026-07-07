/**
 * GREEN App — Layout Engine
 * Generates and injects the sidebar and header HTML into every
 * inner (post-login) page. Handles navigation, mobile toggle,
 * and user info display from the saved session.
 *
 * Usage on each protected page:
 *   Layout.init({ page: 'dashboard', title: 'Dashboard', subtitle: '...' });
 */

/* ============================================================
   NAVIGATION DEFINITION
   Single source of truth — add/remove pages here only.
   ============================================================ */
const NAV_ITEMS = [
  {
    section: 'MAIN',
    items: [
      {
        id: 'dashboard',
        label: 'Dashboard',
        href: '/dashboard',
        icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></svg>`
      },
      {
        id: 'map',
        label: 'GREEN Map',
        href: '/map',
        icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"/><circle cx="12" cy="10" r="3"/></svg>`
      },
      {
        id: 'camera',
        label: 'Drone Analysis',
        href: '/camera',
        icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M23 7l-7 5 7 5V7z"/><rect x="1" y="5" width="15" height="14" rx="2" ry="2"/></svg>`
      },
      {
        id: 'chatbot',
        label: 'GreenBot',
        href: '/chatbot',
        badge: 'AI',
        icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/><circle cx="9" cy="10" r="1" fill="currentColor" stroke="none"/><circle cx="12" cy="10" r="1" fill="currentColor" stroke="none"/><circle cx="15" cy="10" r="1" fill="currentColor" stroke="none"/></svg>`
      },
    ]
  },
  {
    section: 'ANALYTICS',
    items: [
      {
        id: 'diseases',
        label: 'Disease Database',
        href: '/diseases',
        icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><polyline points="10 9 9 9 8 9"/></svg>`
      },
      {
        id: 'calendar',
        label: 'Ag. Calendar',
        href: '/calendar',
        icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="18" rx="2" ry="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg>`
      },
      {
        id: 'economics',
        label: 'Economic Scenarios',
        href: '/economics',
        icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><polyline points="23 6 13.5 15.5 8.5 10.5 1 18"/><polyline points="17 6 23 6 23 12"/></svg>`
      },
      {
        id: 'benchmark',
        label: 'Local Benchmark',
        href: '/benchmark',
        icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>`
      },
    ]
  },
  {
    section: 'OPERATIONS',
    items: [
      {
        id: 'marketplace',
        label: 'Marketplace',
        href: '/marketplace',
        icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M6 2L3 6v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6l-3-4z"/><line x1="3" y1="6" x2="21" y2="6"/><path d="M16 10a4 4 0 0 1-8 0"/></svg>`
      },
      {
        id: 'history',
        label: 'Analysis History',
        href: '/history',
        icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>`
      },
    ]
  },
  {
    section: 'ACCOUNT',
    items: [
      {
        id: 'settings',
        label: 'Settings',
        href: '/settings',
        icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>`
      },
    ]
  }
];


/* ============================================================
   LAYOUT ENGINE
   ============================================================ */
const Layout = {

  /** Currently active page id (set by init()) */
  currentPage: null,

  /**
   * Initialise the full app shell: sidebar + header.
   * Call this at the top of every protected page's script.
   *
   * @param {object} config
   *   @param {string} config.page      - Page id matching NAV_ITEMS (e.g. 'dashboard')
   *   @param {string} config.title     - Header title (e.g. 'Dashboard')
   *   @param {string} [config.subtitle]- Optional header subtitle / breadcrumb
   */
  init({ page, title, subtitle = 'GREEN Enterprise Platform' }) {
    this.currentPage = page;

    // Inject CSS dependency guard
    this._ensureCSSLoaded();

    // Build and inject the shell elements
    this._injectSidebar();
    this._injectHeader(title, subtitle);
    this._injectMobileOverlay();

    // Update user info from saved session
    this._updateUserDisplay();

    // Bind mobile sidebar toggle
    this._bindMobileToggle();

    // Mark current nav item as active
    this._setActiveNav(page);
  },

  /* ----------------------------------------------------------
     SIDEBAR HTML
     ---------------------------------------------------------- */
  _injectSidebar() {
    // Build all navigation sections HTML
    let navHTML = '';
    NAV_ITEMS.forEach(section => {
      navHTML += `
        <div class="nav-section">
          <span class="nav-section-label">${section.section}</span>
        </div>`;

      section.items.forEach(item => {
        const badge = item.badge
          ? `<span class="nav-badge">${item.badge}</span>`
          : '';
        navHTML += `
        <a href="${item.href}"
           class="nav-item"
           data-page="${item.id}"
           data-label="${item.label}">
          <span class="nav-icon">${item.icon}</span>
          <span class="nav-item-label">${item.label}</span>
          ${badge}
        </a>`;
      });
    });

    const sidebarHTML = `
      <aside class="sidebar" id="appSidebar" role="navigation" aria-label="Main navigation">

        <!-- Logo -->
        <a href="/dashboard" class="sidebar-logo" aria-label="GREEN Home">
          <img src="/assets/logo.jpeg" alt="GREEN Logo" />
          <span class="sidebar-logo-name">GREEN</span>
        </a>

        <!-- Navigation -->
        <nav class="sidebar-nav" id="sidebarNav">
          ${navHTML}
          <div class="nav-divider"></div>
        </nav>

        <!-- User card at bottom -->
        <div class="sidebar-user">
          <a href="/profile" class="sidebar-user-inner" id="sidebarUserCard">
            <div class="user-avatar" id="sidebarUserAvatar">--</div>
            <div class="sidebar-user-info">
              <div class="sidebar-user-name" id="sidebarUserName">Loading...</div>
              <div class="sidebar-user-company" id="sidebarUserCompany">GREEN Platform</div>
            </div>
            <!-- Chevron right icon -->
            <svg class="sidebar-user-chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <polyline points="9 18 15 12 9 6"/>
            </svg>
          </a>
        </div>

      </aside>`;

    // Insert before #appMain (or as the first child of #appLayout)
    const layout = document.getElementById('appLayout');
    if (layout) {
      layout.insertAdjacentHTML('afterbegin', sidebarHTML);
    }
  },

  /* ----------------------------------------------------------
     HEADER HTML
     ---------------------------------------------------------- */
  _injectHeader(title, subtitle) {
    const headerHTML = `
      <header class="app-header" id="appHeader">

        <!-- Left: hamburger + title -->
        <div class="header-left">
          <!-- Mobile hamburger -->
          <button class="header-menu-toggle" id="headerMenuToggle" aria-label="Toggle sidebar">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <line x1="3" y1="12" x2="21" y2="12"/>
              <line x1="3" y1="6" x2="21" y2="6"/>
              <line x1="3" y1="18" x2="21" y2="18"/>
            </svg>
          </button>

          <!-- Page title -->
          <div class="header-title-area">
            <div class="header-page-title">${title}</div>
            <div class="header-breadcrumb">${subtitle}</div>
          </div>
        </div>

        <!-- Right: notifications + user -->
        <div class="header-right">

          <!-- Notification bell -->
          <button class="header-icon-btn" id="headerNotifBtn" aria-label="Notifications" title="Notifications">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/>
              <path d="M13.73 21a2 2 0 0 1-3.46 0"/>
            </svg>
            <span class="notif-badge" id="headerNotifBadge" style="display:none;"></span>
          </button>

          <div class="header-divider"></div>

          <!-- User avatar + name (links to profile) -->
          <a href="/profile" class="header-user-btn" id="headerUserBtn" aria-label="Go to profile">
            <div class="user-avatar" id="headerUserAvatar" style="width:32px;height:32px;font-size:0.75rem;">--</div>
            <span class="header-user-name" id="headerUserName">...</span>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <polyline points="6 9 12 15 18 9"/>
            </svg>
          </a>

        </div>
      </header>`;

    // Insert at the top of #appMain
    const main = document.getElementById('appMain');
    if (main) {
      main.insertAdjacentHTML('afterbegin', headerHTML);
    }
  },

  /* ----------------------------------------------------------
     MOBILE OVERLAY
     ---------------------------------------------------------- */
  _injectMobileOverlay() {
    document.body.insertAdjacentHTML('beforeend',
      '<div class="sidebar-overlay" id="sidebarOverlay"></div>'
    );
  },

  /* ----------------------------------------------------------
     SIDEBAR TOGGLE — desktop collapse + mobile slide
     ---------------------------------------------------------- */
  _bindMobileToggle() {
    const toggle  = document.getElementById('headerMenuToggle');
    const sidebar = document.getElementById('appSidebar');
    const overlay = document.getElementById('sidebarOverlay');

    if (!toggle || !sidebar || !overlay) return;

    const isMobile = () => window.innerWidth <= 768;

    // ── Desktop collapse/expand (persisted in localStorage) ───
    const STORAGE_KEY = 'green_sidebar_collapsed';

    const applyCollapsed = (collapsed) => {
      sidebar.classList.toggle('collapsed', collapsed);
      document.body.classList.toggle('sidebar-collapsed', collapsed);
      localStorage.setItem(STORAGE_KEY, collapsed ? '1' : '0');
    };

    // Restore saved desktop state on load (desktop only)
    if (!isMobile() && localStorage.getItem(STORAGE_KEY) === '1') {
      applyCollapsed(true);
    }

    // ── Mobile drawer open/close ───────────────────────────────
    const openMobile = () => {
      sidebar.classList.add('open');
      overlay.classList.add('visible');
      document.body.style.overflow = 'hidden';
    };
    const closeMobile = () => {
      sidebar.classList.remove('open');
      overlay.classList.remove('visible');
      document.body.style.overflow = '';
    };

    // ── Single toggle button — behaviour depends on viewport ───
    toggle.addEventListener('click', () => {
      if (isMobile()) {
        sidebar.classList.contains('open') ? closeMobile() : openMobile();
      } else {
        applyCollapsed(!sidebar.classList.contains('collapsed'));
      }
    });

    // Clicking the overlay closes the mobile drawer
    overlay.addEventListener('click', closeMobile);

    // Close mobile drawer when a nav link is clicked
    document.querySelectorAll('.nav-item').forEach(item => {
      item.addEventListener('click', () => { if (isMobile()) closeMobile(); });
    });

    // When resizing from mobile to desktop, clean up mobile state
    window.addEventListener('resize', () => {
      if (!isMobile()) {
        closeMobile();
        // Re-apply persisted desktop collapsed state
        if (localStorage.getItem(STORAGE_KEY) === '1') {
          applyCollapsed(true);
        }
      }
    });
  },

  /* ----------------------------------------------------------
     ACTIVE NAV STATE
     ---------------------------------------------------------- */
  _setActiveNav(pageId) {
    document.querySelectorAll('.nav-item').forEach(el => {
      if (el.dataset.page === pageId) {
        el.classList.add('active');
        el.setAttribute('aria-current', 'page');
      } else {
        el.classList.remove('active');
      }
    });
  },

  /* ----------------------------------------------------------
     USER DISPLAY — read from Auth session cache
     ---------------------------------------------------------- */
  _updateUserDisplay() {
    const user = (typeof Auth !== 'undefined') ? Auth.getUser() : null;
    if (!user) return;

    const initials = (typeof getInitials !== 'undefined')
      ? getInitials(user.first_name, user.last_name)
      : ((user.first_name || '')[0] + (user.last_name || '')[0]).toUpperCase();

    const fullName    = `${user.first_name || ''} ${user.last_name || ''}`.trim();
    const companyName = user.company_name || user.region || 'GREEN Platform';

    // Sidebar user card
    const sidebarAvatar  = document.getElementById('sidebarUserAvatar');
    const sidebarName    = document.getElementById('sidebarUserName');
    const sidebarCompany = document.getElementById('sidebarUserCompany');

    if (sidebarAvatar)  sidebarAvatar.textContent  = initials;
    if (sidebarName)    sidebarName.textContent     = fullName;
    if (sidebarCompany) sidebarCompany.textContent  = companyName;

    // Header user button
    const headerAvatar = document.getElementById('headerUserAvatar');
    const headerName   = document.getElementById('headerUserName');

    if (headerAvatar) headerAvatar.textContent = initials;
    if (headerName)   headerName.textContent   = user.first_name || fullName;
  },

  /* ----------------------------------------------------------
     CSS GUARD — warn if stylesheets not loaded
     ---------------------------------------------------------- */
  _ensureCSSLoaded() {
    if (!document.querySelector('link[href*="app.css"]')) {
      console.warn('[GREEN Layout] app.css not loaded. Add it to your page <head>.');
    }
  },

  /* ----------------------------------------------------------
     PUBLIC API
     ---------------------------------------------------------- */

  /**
   * Update the user display after a profile edit.
   * Call this from the profile page after successful update.
   */
  refreshUser() {
    this._updateUserDisplay();
  },

  /**
   * Set the notification badge visible/hidden.
   * @param {boolean} visible
   */
  setNotificationBadge(visible) {
    const badge = document.getElementById('headerNotifBadge');
    if (badge) badge.style.display = visible ? 'block' : 'none';
  }
};
