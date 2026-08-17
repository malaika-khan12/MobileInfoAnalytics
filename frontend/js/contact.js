// js/contact.js - Enhanced Contact Form Handler

const form = document.getElementById('contactForm');
const btn = document.getElementById('sendBtn');
const toast = document.getElementById('toast');

/**
 * Show toast notification
 */
function showToast(message, success = true) {
  toast.textContent = message;
  toast.className = 'toast show ' + (success ? 'ok' : 'bad');
  
  // Auto-hide after 4 seconds
  setTimeout(() => {
    toast.className = 'toast';
  }, 4000);
}

/**
 * Validate form fields
 */
function validateForm() {
  const name = document.getElementById('name').value.trim();
  const email = document.getElementById('email').value.trim();
  const message = document.getElementById('message').value.trim();
  
  if (!name || name.length < 2) {
    showToast('Please enter a valid name.', false);
    return false;
  }
  
  if (!email || !email.includes('@')) {
    showToast('Please enter a valid email address.', false);
    return false;
  }
  
  if (!message || message.length < 10) {
    showToast('Please enter a message (at least 10 characters).', false);
    return false;
  }
  
  return true;
}

/**
 * Handle form submission
 */
if (form) {
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    
    // Validate before sending
    if (!validateForm()) {
      return;
    }
    
    // Update button state
    const originalText = btn.innerHTML;
    btn.innerHTML = `
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <circle cx="12" cy="12" r="10"></circle>
        <polyline points="12 6 12 12 16 14"></polyline>
      </svg>
      Sending...
    `;
    btn.disabled = true;
    
    try {
      const response = await fetch(form.action, {
        method: 'POST',
        body: new FormData(form),
        headers: {
          'Accept': 'application/json'
        }
      });
      
      if (!response.ok) {
        throw new Error('Network response was not ok');
      }
      
      // Success
      form.reset();
      showToast('Message sent successfully! I\'ll get back to you soon.', true);
      
      // Add success animation to button
      btn.innerHTML = `
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <polyline points="20 6 9 17 4 12"></polyline>
        </svg>
        Sent!
      `;
      
      // Reset button after delay
      setTimeout(() => {
        btn.innerHTML = originalText;
        btn.disabled = false;
      }, 3000);
      
    } catch (error) {
      // Error handling
      console.error('Form submission error:', error);
      showToast('Something went wrong. Please try again or email me directly.', false);
      
      // Reset button
      btn.innerHTML = originalText;
      btn.disabled = false;
    }
  });
}

/**
 * Add character counter to textarea
 */
const messageField = document.getElementById('message');
if (messageField) {
  const minChars = 10;
  
  messageField.addEventListener('input', (e) => {
    const length = e.target.value.length;
    
    // Update aria-label for accessibility
    if (length < minChars) {
      e.target.setAttribute('aria-label', `Message (${minChars - length} more characters needed)`);
    } else {
      e.target.setAttribute('aria-label', 'Message');
    }
  });
}
