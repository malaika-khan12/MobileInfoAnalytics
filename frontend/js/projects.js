// js/projects.js - Project Cards + Modal (2-per-row layout, no subtitle on cards)

// Use static project data from projects-data.js
const projects = window.PROJECTS || [];
const filters = window.PROJECT_DOMAINS || [
  { key: 'all', label: 'All Projects' },
  { key: 'health', label: 'Healthcare AI' },
  { key: 'finance', label: 'Quantitative Finance' },
  { key: 'risk', label: 'Marketing & Risk Prediction' },
  { key: 'tech', label: 'Technology & Data Science' }
];

// DOM Elements
const grid = document.getElementById('projectsGrid');
const filterRow = document.getElementById('filterRow');
const modal = document.getElementById('projectModal');

// State
let activeFilter = 'all';

/**
 * Render filter pills
 */
function renderFilters() {
  filterRow.innerHTML = '';

  filters.forEach(f => {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'filter-pill' + (f.key === activeFilter ? ' active' : '');
    button.textContent = f.label;
    button.setAttribute('aria-pressed', f.key === activeFilter);

    button.addEventListener('click', () => {
      activeFilter = f.key;
      renderFilters();
      renderProjects();

      // Update URL without page reload
      const url = new URL(window.location);
      if (f.key === 'all') url.searchParams.delete('filter');
      else url.searchParams.set('filter', f.key);
      window.history.replaceState({}, '', url);
    });

    filterRow.appendChild(button);
  });
}

/**
 * Check if project matches current filter
 */
function matches(project) {
  const domainMatch = Array.isArray(project.domain) 
    ? project.domain.includes(activeFilter) 
    : project.domain === activeFilter;

  return (
    activeFilter === 'all' ||
    domainMatch ||
    (Array.isArray(project.tags) && project.tags.includes(activeFilter))
  );
}

/**
 * Render project cards
 */
function renderProjects() {
  grid.innerHTML = '';

  const filteredProjects = projects.filter(matches);

  // Empty state
  if (filteredProjects.length === 0) {
    const empty = document.createElement('div');
    empty.className = 'card no-hover';
    empty.style.padding = 'var(--space-3xl)';
    empty.style.textAlign = 'center';
    empty.innerHTML = `
      <b>No projects found</b>
      <p class="muted">Try selecting a different filter category.</p>
    `;
    grid.appendChild(empty);
    return;
  }

  filteredProjects.forEach((project, index) => {
    const card = document.createElement('article');
    card.className = 'project-card card';
    card.tabIndex = 0;
    card.setAttribute('role', 'button');
    card.setAttribute('aria-label', `View details for ${project.title}`);
    card.style.animationDelay = `${index * 50}ms`;

    const safeTags = Array.isArray(project.tags) ? project.tags : [];

    // NOTE: subtitle intentionally removed from card markup
    card.innerHTML = `
      <img class="thumb" src="${project.image}" alt="${project.title}" loading="lazy"
           onerror="this.src='pictures/favicon.png'" />
      <div>
        <div class="pname">${project.title}</div>
        <div class="card-tags">
          ${safeTags.slice(0, 4).map(tag => considerTag(tag)).join('')}
          ${safeTags.length > 4 ? `<span>+${safeTags.length - 4}</span>` : ''}
        </div>
      </div>
    `;

    card.addEventListener('click', () => openModal(project));
    card.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        openModal(project);
      }
    });

    grid.appendChild(card);
  });

  const announcement = `Showing ${filteredProjects.length} project${filteredProjects.length !== 1 ? 's' : ''}`;
  grid.setAttribute('aria-label', announcement);
}

function considerTag(tag) {
  // simple guard: stringify + basic escape via textContent trick
  const span = document.createElement('span');
  span.textContent = String(tag);
  return span.outerHTML;
}

/**
 * Open project detail modal
 */
function openModal(project) {
  document.getElementById('modalImg').src = project.image;
  document.getElementById('modalImg').alt = project.title;
  document.getElementById('modalTitle').textContent = project.title;
  document.getElementById('modalSubtitle').textContent = project.subtitle || '';
  document.getElementById('modalDesc').textContent = project.description || '';

  const tagsContainer = document.getElementById('modalTags');
  const safeTags = Array.isArray(project.tags) ? project.tags : [];
  tagsContainer.innerHTML = safeTags.map(tag => `<span>${tag}</span>`).join('');

  const liveBtn = document.getElementById('modalLive');
  const repoBtn = document.getElementById('modalRepo');

  if (project.live && project.live.trim() !== '') {
    liveBtn.href = project.live;
    liveBtn.style.display = 'inline-flex';
  } else {
    liveBtn.style.display = 'none';
  }

  repoBtn.href = project.repo || '#';

  // Update URL hash
  window.location.hash = project.id;

  // Show modal
  modal.classList.add('open');
  modal.setAttribute('aria-hidden', 'false');

  // Prevent background scroll
  document.body.style.overflow = 'hidden';

  // Focus close button
  setTimeout(() => {
    const closeBtn = modal.querySelector('.modal-close');
    if (closeBtn) closeBtn.focus();
  }, 100);
}

/**
 * Close modal
 */
function closeModal() {
  modal.classList.remove('open');
  modal.setAttribute('aria-hidden', 'true');
  document.body.style.overflow = '';

  // Remove hash safely (keep path + query)
  const url = new URL(window.location.href);
  url.hash = '';
  window.history.replaceState({}, '', url);
}

/**
 * Setup modal close handlers
 */
function setupModalHandlers() {
  modal.addEventListener('click', (e) => {
    if (e.target && e.target.dataset && e.target.dataset.close === 'true') {
      closeModal();
    }
  });

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && modal.classList.contains('open')) {
      closeModal();
    }
  });
}

/**
 * Initialize from URL parameters
 */
function initFromURL() {
  const params = new URLSearchParams(window.location.search);

  const filterParam = params.get('filter');
  if (filterParam && filters.some(f => f.key === filterParam)) {
    activeFilter = filterParam;
  }

  const hash = window.location.hash.slice(1);
  if (hash) {
    const project = projects.find(p => p.id === hash);
    if (project) setTimeout(() => openModal(project), 200);
  }
}

/**
 * Initialize projects page
 */
function init() {
  initFromURL();
  renderFilters();
  renderProjects();
  setupModalHandlers();
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', init);
} else {
  init();
}
