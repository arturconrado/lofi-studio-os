/* A secure same-origin cookie keeps authenticated actions usable across tabs. */
window.studioCSRF=()=>{const value=String(document.cookie||'').split(';').map(v=>v.trim()).find(v=>v.startsWith('lofi_csrf='));return value?decodeURIComponent(value.slice('lofi_csrf='.length)):(sessionStorage.getItem('lofi_csrf')||'');};
