export function bindProfileMenu({ onOpenAdmin, onOpenModelSettings }) {
    const toggle = document.getElementById('v2ProfileToggle');
    const menu = document.getElementById('v2ProfileMenu');
    if (!toggle || !menu) return;

    toggle.addEventListener('click', () => {
        const hidden = menu.classList.toggle('hidden');
        toggle.setAttribute('aria-expanded', hidden ? 'false' : 'true');
    });

    document.addEventListener('click', (event) => {
        if (menu.classList.contains('hidden')) return;
        if (menu.contains(event.target) || toggle.contains(event.target)) return;
        menu.classList.add('hidden');
        toggle.setAttribute('aria-expanded', 'false');
    });

    document.getElementById('v2OpenAdminSettings')?.addEventListener('click', () => {
        menu.classList.add('hidden');
        onOpenAdmin?.();
    });
    document.getElementById('v2OpenModelSettings')?.addEventListener('click', () => {
        menu.classList.add('hidden');
        onOpenModelSettings?.();
    });
    document.getElementById('v2LogoutBtn')?.addEventListener('click', async () => {
        await fetch('/api/auth/logout', { method: 'POST', credentials: 'include' }).catch(() => {});
        window.location.href = '/login';
    });
}

export function bindModalCloseButtons() {
    document.querySelectorAll('[data-close-modal]').forEach((button) => {
        button.addEventListener('click', () => {
            document.getElementById(button.dataset.closeModal)?.classList.add('hidden');
        });
    });
}
