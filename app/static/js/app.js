/* ═══════════════════════════════════════════════════════════════
   HCS App Logic — sidebar, toast, CSRF, global helpers
   ═══════════════════════════════════════════════════════════════ */

// ─── Sidebar Toggle ─────────────────────────────────────────────
(function initSidebar() {
    const layout = document.querySelector('.app-layout');
    if (!layout) return;

    const saved = localStorage.getItem('hcs-sidebar-collapsed');
    if (saved === 'true') {
        layout.classList.add('collapsed');
    }

    window.toggleSidebar = function () {
        layout.classList.toggle('collapsed');
        localStorage.setItem(
            'hcs-sidebar-collapsed',
            layout.classList.contains('collapsed')
        );
    };
})();

// ─── User Dropdown ──────────────────────────────────────────────
document.addEventListener('click', function (e) {
    const dropdowns = document.querySelectorAll('.user-dropdown.open');
    dropdowns.forEach(function (dd) {
        if (!dd.parentElement.contains(e.target)) {
            dd.classList.remove('open');
        }
    });
});

function toggleUserMenu(event) {
    event.stopPropagation();
    const dd = document.querySelector('.user-dropdown');
    if (dd) dd.classList.toggle('open');
}

// ─── CSRF ───────────────────────────────────────────────────────
function getCsrfToken() {
    const match = document.cookie.match(/(?:^|;\s*)csrf_token=([^;]*)/);
    return match ? decodeURIComponent(match[1]) : '';
}

// Monkey-patch fetch to auto-attach CSRF on mutating /api/ calls
const _originalFetch = window.fetch;
window.fetch = function (url, options) {
    options = options || {};
    if (
        typeof url === 'string' &&
        url.startsWith('/api/') &&
        options.method &&
        options.method !== 'GET'
    ) {
        options.headers = options.headers || {};
        options.headers['X-CSRF-Token'] = getCsrfToken();
    }
    return _originalFetch.call(this, url, options);
};

// ─── Toast Notifications ────────────────────────────────────────
(function initToasts() {
    let container = document.querySelector('.toast-container');
    if (!container) {
        container = document.createElement('div');
        container.className = 'toast-container';
        document.body.appendChild(container);
    }

    window.showNotification = function (message, type) {
        type = type || 'success';
        const toast = document.createElement('div');
        toast.className = 'toast ' + type;
        toast.textContent = message;
        container.appendChild(toast);

        setTimeout(function () {
            toast.classList.add('leaving');
            setTimeout(function () { toast.remove(); }, 250);
        }, 3500);
    };
})();

// ─── Start Scan ─────────────────────────────────────────────────
async function startScan() {
    if (!confirm('Запустить новое сканирование?')) return;

    try {
        const response = await fetch('/api/scans', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ started_by: 'ui' }),
        });
        const data = await response.json();

        if (response.ok) {
            showNotification('Сканирование запущено', 'success');
            setTimeout(function () { window.location.reload(); }, 1200);
        } else {
            showNotification('Ошибка: ' + data.error, 'danger');
        }
    } catch (e) {
        showNotification('Ошибка: ' + e.message, 'danger');
    }
}
