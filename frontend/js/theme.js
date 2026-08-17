// js/theme.js - Enhanced Theme Management

const THEME_KEY = 'ih_portfolio_theme';
const themeBtn = document.getElementById('themeBtn');
const themeIcon = document.getElementById('themeIcon');

// SVG icons for theme toggle
const icons = {
  light: `
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <circle cx="12" cy="12" r="5"/>
      <line x1="12" y1="1" x2="12" y2="3"/>
      <line x1="12" y1="21" x2="12" y2="23"/>
      <line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/>
      <line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/>
      <line x1="1" y1="12" x2="3" y2="12"/>
      <line x1="21" y1="12" x2="23" y2="12"/>
      <line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/>
      <line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/>
    </svg>
  `,
  dark: `
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>
    </svg>
  `
};

/**
 * Get system theme preference
 */
function getSystemTheme() {
  if (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) {
    return 'dark';
  }
  return 'light';
}

/**
 * Set theme and update UI
 */
function setTheme(theme, skipTransition = false) {
  // Skip transitions during initial load for smoother experience
  if (skipTransition) {
    document.documentElement.classList.add('no-transition');
  }

  document.documentElement.setAttribute('data-theme', theme);
  localStorage.setItem(THEME_KEY, theme);
  
  // Update icon
  if (themeIcon) {
    themeIcon.innerHTML = icons[theme] || icons.light;
  }

  // Update button title
  if (themeBtn) {
    themeBtn.setAttribute('title', `Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`);
    themeBtn.setAttribute('aria-label', `Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`);
  }

  // Re-enable transitions
  if (skipTransition) {
    setTimeout(() => {
      document.documentElement.classList.remove('no-transition');
    }, 50);
  }
}

/**
 * Initialize theme on page load
 */
function initTheme() {
  const savedTheme = localStorage.getItem(THEME_KEY);
  const initialTheme = savedTheme || getSystemTheme();
  setTheme(initialTheme, true); // Skip transition on initial load
}

/**
 * Setup theme toggle button
 */
function setupThemeToggle() {
  if (!themeBtn || !themeIcon) return;

  themeBtn.addEventListener('click', () => {
    const currentTheme = document.documentElement.getAttribute('data-theme') || 'light';
    const nextTheme = currentTheme === 'dark' ? 'light' : 'dark';
    setTheme(nextTheme);

    // Add pulse animation to button
    themeBtn.style.transform = 'scale(0.9)';
    setTimeout(() => {
      themeBtn.style.transform = '';
    }, 150);
  });
}

/**
 * Listen for system theme changes
 */
function setupSystemThemeListener() {
  if (!window.matchMedia) return;

  const darkModeQuery = window.matchMedia('(prefers-color-scheme: dark)');
  
  darkModeQuery.addEventListener('change', (e) => {
    // Only auto-switch if user hasn't manually set a preference
    const savedTheme = localStorage.getItem(THEME_KEY);
    if (!savedTheme) {
      setTheme(e.matches ? 'dark' : 'light');
    }
  });
}

// Initialize theme immediately to prevent flash
initTheme();

// Setup event listeners when DOM is ready
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', () => {
    setupThemeToggle();
    setupSystemThemeListener();
  });
} else {
  setupThemeToggle();
  setupSystemThemeListener();
}

// Add CSS for no-transition class
const style = document.createElement('style');
style.textContent = '.no-transition * { transition: none !important; }';
document.head.appendChild(style);
