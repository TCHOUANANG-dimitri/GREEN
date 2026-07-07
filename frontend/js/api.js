/**
 * GREEN App — API Client
 * Centralised HTTP calls to the FastAPI backend.
 * All requests go through the `request()` function which
 * handles auth headers, error parsing, and response formatting.
 *
 * Usage example:
 *   const { data, error } = await API.auth.login({ identifier, password });
 */

/* ============================================================
   BASE CONFIGURATION
   ============================================================ */

/**
 * Base URL for all API calls.
 * In development, FastAPI runs on http://localhost:8000
 * In production, use a relative path (same origin).
 */
const API_BASE_URL = 'http://localhost:8000';


/* ============================================================
   CORE REQUEST FUNCTION
   All API methods use this — handles headers, auth, and errors.
   ============================================================ */

/**
 * Make an HTTP request to the GREEN API.
 *
 * @param {string} endpoint  - Path relative to API_BASE_URL (e.g. '/api/auth/login')
 * @param {string} method    - HTTP method ('GET', 'POST', 'PUT', 'DELETE')
 * @param {object|null} body - Request body (will be JSON-serialised)
 * @param {boolean} auth     - Include the Authorization header?
 * @param {boolean} isForm   - Use FormData instead of JSON? (for file uploads)
 *
 * @returns {Promise<{data: any, error: string|null, status: number}>}
 *   Always resolves (never throws), returns either data or an error message.
 */
async function request(endpoint, method = 'GET', body = null, auth = false, isForm = false) {
  const headers = {};

  // Add auth token if required
  if (auth) {
    const token = Auth.getToken();
    if (!token) {
      // No token found — redirect to login
      Auth.clear();
      window.location.replace('/');
      return { data: null, error: 'Not authenticated', status: 401 };
    }
    headers['Authorization'] = `Bearer ${token}`;
  }

  // Set Content-Type for JSON requests (not for FormData — browser sets it automatically)
  if (body && !isForm) {
    headers['Content-Type'] = 'application/json';
  }

  const config = {
    method,
    headers,
  };

  if (body) {
    config.body = isForm ? body : JSON.stringify(body);
  }

  try {
    const response = await fetch(`${API_BASE_URL}${endpoint}`, config);

    // 204 No Content — success with no body (e.g. DELETE).
    // Do NOT try to read the body: it will throw on some browsers.
    if (response.status === 204) {
      return { data: null, error: null, status: 204 };
    }

    const contentType = response.headers.get('content-type') || '';
    const isJson = contentType.includes('application/json');

    const responseData = isJson ? await response.json() : await response.text();

    if (!response.ok) {
      // Extract the error detail from FastAPI's default error format
      const errorMessage = isJson
        ? (responseData.detail || responseData.message || 'Something went wrong.')
        : responseData;
      return { data: null, error: errorMessage, status: response.status };
    }

    return { data: responseData, error: null, status: response.status };

  } catch (networkError) {
    // Network failure (server offline, CORS, etc.)
    console.error('[GREEN API] Network error:', networkError);
    return {
      data: null,
      error: 'Unable to connect to the server. Please check your connection.',
      status: 0
    };
  }
}


/* ============================================================
   API NAMESPACES
   Organised by feature domain — mirrors backend router structure.
   ============================================================ */

const API = {

  /* ----------------------------------------------------------
     AUTH
     ---------------------------------------------------------- */
  auth: {
    /**
     * Register a new account.
     * @param {object} payload - { first_name, last_name, phone, email?, password, company_name?, region? }
     */
    register(payload) {
      return request('/api/auth/register', 'POST', payload);
    },

    /**
     * Sign in with phone or email + password.
     * @param {object} payload - { identifier, password }
     */
    login(payload) {
      return request('/api/auth/login', 'POST', payload);
    },

    /** Get the current user's profile (requires auth). */
    me() {
      return request('/api/auth/me', 'GET', null, true);
    },

    /**
     * Update profile fields.
     * @param {object} payload - Any of { first_name, last_name, email, company_name, region }
     */
    updateProfile(payload) {
      return request('/api/auth/me', 'PUT', payload, true);
    },

    /**
     * Change password.
     * @param {object} payload - { current_password, new_password }
     */
    changePassword(payload) {
      return request('/api/auth/change-password', 'POST', payload, true);
    },

    /** Deactivate the current account. */
    deleteAccount() {
      return request('/api/auth/me', 'DELETE', null, true);
    }
  },

  /* ----------------------------------------------------------
     HEALTH CHECK
     ---------------------------------------------------------- */
  health() {
    return request('/api/health', 'GET');
  },

  /* ----------------------------------------------------------
     DISEASE ANALYSIS  (Phase 4 — added later)
     ---------------------------------------------------------- */
  analysis: {
    /** Upload an image for disease detection. */
    uploadImage(formData) {
      return request('/api/analysis/upload', 'POST', formData, true, true);
    },

    /** Get analysis history for the current user with optional server-side filters. */
    history(limit = 20, offset = 0, filters = {}) {
      const p = new URLSearchParams({ limit, offset });
      if (filters.source)      p.set('source',      filters.source);
      if (filters.result_type) p.set('result_type', filters.result_type);
      if (filters.plant_type)  p.set('plant_type',  filters.plant_type);
      return request(`/api/analysis/history?${p}`, 'GET', null, true);
    },

    /** Get a specific analysis by ID (including the fiche terrain). */
    get(id) {
      return request(`/api/analysis/${id}`, 'GET', null, true);
    },

    /** Delete an analysis from history. */
    delete(id) {
      return request(`/api/analysis/${id}`, 'DELETE', null, true);
    }
  },

  /* ----------------------------------------------------------
     CHATBOT (GreenBot) — Phase 6
     ---------------------------------------------------------- */
  chat: {
    /** Start a new chat session. */
    createSession() {
      return request('/api/chat/sessions', 'POST', {}, true);
    },

    /** Get all chat sessions for the current user. */
    sessions() {
      return request('/api/chat/sessions', 'GET', null, true);
    },

    /** Get a session with all its messages. */
    getSession(sessionId) {
      return request(`/api/chat/sessions/${sessionId}`, 'GET', null, true);
    },

    /**
     * Send a message and get GreenBot's reply.
     * @param {number} sessionId
     * @param {string} content - The user's message.
     * @param {number|null} analysisId - Optional: link to a disease analysis.
     */
    sendMessage(sessionId, content, analysisId = null) {
      return request(`/api/chat/sessions/${sessionId}/messages`, 'POST', {
        content,
        analysis_id: analysisId
      }, true);
    },

    /** Delete a chat session and all its messages. */
    deleteSession(sessionId) {
      return request(`/api/chat/sessions/${sessionId}`, 'DELETE', null, true);
    }
  },

  /* ----------------------------------------------------------
     PARCELS (GREEN Map) — Phase 5
     ---------------------------------------------------------- */
  parcels: {
    /** Get all parcels for the current user. */
    list() {
      return request('/api/parcels', 'GET', null, true);
    },

    /** Create a new parcel. */
    create(payload) {
      return request('/api/parcels', 'POST', payload, true);
    },

    /** Update parcel data (name, geometry, crop, etc.). */
    update(id, payload) {
      return request(`/api/parcels/${id}`, 'PUT', payload, true);
    },

    /** Delete a parcel. */
    delete(id) {
      return request(`/api/parcels/${id}`, 'DELETE', null, true);
    }
  },

  /* ----------------------------------------------------------
     DRONE — Phase 4
     ---------------------------------------------------------- */
  drone: {
    /**
     * Connect to a drone by IP address.
     * Backend verifies the MJPEG stream is reachable.
     * @param {string} ip - e.g. "192.168.10.1"
     * @param {number|string} port - e.g. 8080
     */
    connect(ip, port = 8080) {
      return request('/api/drone/connect', 'POST', { ip, port }, true);
    },

    /**
     * Capture a frame from the drone MJPEG stream and run inference.
     * @param {string} ip
     * @param {number|string} port
     * @param {number|null} parcelId
     * @param {number|null} latitude
     * @param {number|null} longitude
     */
    captureAndAnalyze(ip, port = 8080, parcelId = null, latitude = null, longitude = null) {
      return request('/api/drone/capture', 'POST', {
        ip, port, parcel_id: parcelId, latitude, longitude
      }, true);
    },

    /**
     * Upload a local image file for disease inference.
     * @param {FormData} formData - must contain 'file' field
     */
    upload(formData) {
      return request('/api/drone/upload', 'POST', formData, true, true);
    },

    /**
     * Get the MJPEG stream URL for a given IP.
     * @param {string} ip
     * @param {number|string} port
     */
    streamUrl(ip, port = 8080) {
      return request(`/api/drone/stream-url?ip=${encodeURIComponent(ip)}&port=${encodeURIComponent(port)}`, 'GET', null, true);
    }
  },

  /* ----------------------------------------------------------
     CAMERA / ROVER — Phase MVP (replaces drone for MVP)
     ---------------------------------------------------------- */
  camera: {
    /** Verify rover camera stream is reachable at given IP. */
    connect(ip, port = 8080) {
      return request('/api/camera/connect', 'POST', { ip, port }, true);
    },

    /** Grab one frame from the MJPEG stream and run both AI models. */
    captureFromStream(ip, port = 8080, parcelId = null, latitude = null, longitude = null) {
      return request('/api/camera/capture', 'POST', {
        ip, port, parcel_id: parcelId, latitude, longitude
      }, true);
    },

    /**
     * Send a browser-captured frame (canvas blob) for analysis.
     * @param {FormData} formData - contains 'file' (JPEG blob)
     */
    analyzeFrame(formData) {
      return request('/api/camera/analyze-frame', 'POST', formData, true, true);
    },

    /** Upload a static image for disease analysis. */
    upload(formData) {
      return request('/api/camera/upload', 'POST', formData, true, true);
    },
  },

  /* ----------------------------------------------------------
     DASHBOARD — Phase 3
     ---------------------------------------------------------- */
  dashboard: {
    /** Get summary KPIs for the current user. */
    stats() {
      return request('/api/dashboard/stats', 'GET', null, true);
    },

    /** Get disease trend data for charts. */
    diseaseTrends(days = 30) {
      return request(`/api/dashboard/disease-trends?days=${days}`, 'GET', null, true);
    }
  },

  /* ----------------------------------------------------------
     WEATHER — Phase 6 (OpenWeatherMap proxy)
     ---------------------------------------------------------- */
  weather: {
    /**
     * Get current weather for a Cameroon city or GPS coords.
     * @param {string|null} city  - e.g. 'yaounde', 'douala'
     * @param {number|null} lat   - GPS latitude
     * @param {number|null} lon   - GPS longitude
     */
    current(city = null, lat = null, lon = null) {
      const params = new URLSearchParams();
      if (city) params.set('city', city);
      if (lat !== null) params.set('lat', lat);
      if (lon !== null) params.set('lon', lon);
      return request(`/api/weather/current?${params}`, 'GET', null, true);
    },

    /**
     * Get 5-day daily forecast.
     * @param {string|null} city
     * @param {number|null} lat
     * @param {number|null} lon
     */
    forecast(city = null, lat = null, lon = null) {
      const params = new URLSearchParams();
      if (city) params.set('city', city);
      if (lat !== null) params.set('lat', lat);
      if (lon !== null) params.set('lon', lon);
      return request(`/api/weather/forecast?${params}`, 'GET', null, true);
    }
  },

  /* ----------------------------------------------------------
     DISEASES DATABASE
     ---------------------------------------------------------- */
  diseases: {
    /** Get the full disease database list. */
    list() {
      return request('/api/diseases', 'GET');
    },

    /** Get a specific disease by ID. */
    get(id) {
      return request(`/api/diseases/${id}`, 'GET');
    }
  }
};
