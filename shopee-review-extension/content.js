// Content script - runs on Shopee pages
// This file can be used for additional UI elements or monitoring
console.log('Shopee Review Scraper extension loaded');

// Optional: Add a floating indicator
if (window.location.pathname.includes('/product/')) {
  const indicator = document.createElement('div');
  indicator.id = 'shopee-scraper-indicator';
  indicator.style.cssText = `
    position: fixed;
    bottom: 20px;
    right: 20px;
    width: 50px;
    height: 50px;
    background: #ee4d2d;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    color: white;
    font-size: 24px;
    cursor: pointer;
    z-index: 99999;
    box-shadow: 0 4px 12px rgba(238, 77, 45, 0.4);
    transition: transform 0.2s;
  `;
  indicator.innerHTML = '📝';
  indicator.title = 'Click to open Review Scraper';
  
  indicator.addEventListener('click', () => {
    chrome.runtime.sendMessage({ action: 'OPEN_POPUP' });
  });
  
  indicator.addEventListener('mouseenter', () => {
    indicator.style.transform = 'scale(1.1)';
  });
  
  indicator.addEventListener('mouseleave', () => {
    indicator.style.transform = 'scale(1)';
  });
  
  document.body.appendChild(indicator);
}
