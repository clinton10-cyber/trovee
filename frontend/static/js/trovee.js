// Trovee shared client-side utilities

const Trovee = (() => {
  const TOKEN_KEY = "trovee_token";
  const GEO_KEY = "trovee_geo";

  function getToken() {
    return localStorage.getItem(TOKEN_KEY);
  }

  function setToken(token) {
    localStorage.setItem(TOKEN_KEY, token);
  }

  function clearToken() {
    localStorage.removeItem(TOKEN_KEY);
  }

  function isLoggedIn() {
    return !!getToken();
  }

  async function api(path, { method = "GET", body = null, auth = true } = {}) {
    const headers = { "Content-Type": "application/json" };
    if (auth && getToken()) {
      headers["Authorization"] = `Bearer ${getToken()}`;
    }
    const res = await fetch(path, {
      method,
      headers,
      body: body ? JSON.stringify(body) : null,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      const err = new Error(data.error || "Something went wrong. Please try again.");
      err.status = res.status;
      throw err;
    }
    return data;
  }

  function formatMoney(amount, symbol) {
    const num = Number(amount);
    const formatted = num.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    return `${symbol}${formatted}`;
  }

  function centsToLocal(usdCents, rateInfo) {
    return (usdCents / 100) * (rateInfo?.rate || 1);
  }

  async function detectGeo() {
    const cached = sessionStorage.getItem(GEO_KEY);
    if (cached) return JSON.parse(cached);
    try {
      const geo = await api("/api/geo/detect", { auth: false });
      sessionStorage.setItem(GEO_KEY, JSON.stringify(geo));
      return geo;
    } catch (e) {
      return { country_code: "US", currency_code: "USD", currency_symbol: "$" };
    }
  }

  function showToast(message, type = "default") {
    let toast = document.querySelector(".toast");
    if (!toast) {
      toast = document.createElement("div");
      toast.className = "toast";
      document.body.appendChild(toast);
    }
    toast.textContent = message;
    toast.className = `toast show ${type === "error" ? "error" : ""}`;
    clearTimeout(toast._timer);
    toast._timer = setTimeout(() => toast.classList.remove("show"), 3200);
  }

  function requireAuth() {
    if (!isLoggedIn()) {
      window.location.href = "/login";
    }
  }

  function logout() {
    clearToken();
    window.location.href = "/login";
  }

  return {
    getToken, setToken, clearToken, isLoggedIn, api, formatMoney,
    centsToLocal, detectGeo, showToast, requireAuth, logout,
  };
})();
