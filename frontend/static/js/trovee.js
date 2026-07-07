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

  async function api(path, { method = "GET", body = null, auth = true, headers = {} } = {}) {
    const requestHeaders = {
      "Content-Type": "application/json",
      "Accept": "application/json",
    };

    if (auth && getToken()) {
      requestHeaders["Authorization"] = `Bearer ${getToken()}`;
    }

    for (const key in headers) {
      if (headers.hasOwnProperty(key)) {
        requestHeaders[key] = headers[key];
      }
    }

    let requestBody = null;
    if (body !== null && body !== undefined) {
      if (typeof body === 'object') {
        requestBody = JSON.stringify(body);
      } else if (typeof body === 'string') {
        requestBody = body;
      }
    }

    const options = {
      method: method,
      headers: requestHeaders,
    };

    if (requestBody && ['POST', 'PUT', 'PATCH', 'DELETE'].includes(method.toUpperCase())) {
      options.body = requestBody;
    }

    try {
      const res = await fetch(path, options);
      
      let data;
      const contentType = res.headers.get('content-type');
      if (contentType && contentType.includes('application/json')) {
        data = await res.json();
      } else {
        data = { error: await res.text() || 'Server returned non-JSON response' };
      }

      if (!res.ok) {
        const err = new Error(data.error || data.message || `Request failed with status ${res.status}`);
        err.status = res.status;
        err.data = data;
        throw err;
      }
      
      return data;
    } catch (error) {
      if (error instanceof Error && error.message) {
        throw error;
      }
      throw new Error(error.message || "Something went wrong. Please try again.");
    }
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

  function showToast(message, type) {
    type = type || "default";
    const existing = document.querySelector(".toast");
    if (existing) existing.remove();

    const toast = document.createElement("div");
    toast.className = "toast";
    toast.textContent = message;
    toast.style.cssText = `
      position: fixed;
      bottom: 90px;
      left: 50%;
      transform: translateX(-50%);
      background: ${type === "error" ? '#b91c1c' : '#16a34a'};
      color: white;
      padding: 12px 24px;
      border-radius: 12px;
      font-size: 14px;
      font-weight: 600;
      z-index: 10000;
      max-width: 90%;
      text-align: center;
      box-shadow: 0 4px 20px rgba(0,0,0,0.4);
      transition: all 0.3s ease;
      opacity: 0;
      transform: translateX(-50%) translateY(20px);
    `;
    document.body.appendChild(toast);

    requestAnimationFrame(function() {
      toast.style.opacity = '1';
      toast.style.transform = 'translateX(-50%) translateY(0)';
    });

    clearTimeout(toast._timer);
    toast._timer = setTimeout(function() {
      toast.style.opacity = '0';
      toast.style.transform = 'translateX(-50%) translateY(20px)';
      setTimeout(function() { toast.remove(); }, 300);
    }, 4000);
  }

  function requireAuth() {
    if (!isLoggedIn()) {
      window.location.href = "/login";
      return false;
    }
    return true;
  }

  function logout() {
    clearToken();
    window.location.href = "/login";
  }

  return {
    getToken: getToken,
    setToken: setToken,
    clearToken: clearToken,
    isLoggedIn: isLoggedIn,
    api: api,
    formatMoney: formatMoney,
    centsToLocal: centsToLocal,
    detectGeo: detectGeo,
    showToast: showToast,
    requireAuth: requireAuth,
    logout: logout,
  };
})();

window.Trovee = Trovee;
