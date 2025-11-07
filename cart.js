// ---- Minimal cart store in localStorage ----
const CART_KEY = 'arcana_cart_v1';

function loadCart() {
  try { return JSON.parse(localStorage.getItem(CART_KEY)) || []; }
  catch { return []; }
}
function saveCart(items) {
  localStorage.setItem(CART_KEY, JSON.stringify(items));
  updateCartBadge();
}
function cartCount() {
  return loadCart().reduce((n, it) => n + it.qty, 0);
}
function updateCartBadge() {
  const b = document.querySelector('[data-cart-badge]');
  if (!b) return;
  const n = cartCount();
  b.textContent = n > 0 ? n : '';
  b.style.visibility = n > 0 ? 'visible' : 'hidden';
}
function addToCart(item) {
  // item: {id, name, price, image, qty}
  const cart = loadCart();
  const i = cart.findIndex(x => x.id === item.id);
  if (i >= 0) {
    cart[i].qty += item.qty;
  } else {
    cart.push(item);
  }
  saveCart(cart);
}
function setCartQty(id, qty) {
  const cart = loadCart();
  const i = cart.findIndex(x => x.id === id);
  if (i >= 0) {
    cart[i].qty = Math.max(1, qty|0);
    saveCart(cart);
  }
}
function removeFromCart(id) {
  const cart = loadCart().filter(x => x.id !== id);
  saveCart(cart);
}
document.addEventListener('DOMContentLoaded', updateCartBadge);
