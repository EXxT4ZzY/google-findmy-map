/* Shared bootstrap for both pages: theme + language. Loaded synchronously in
   <head> so the theme and <html lang> are set before the first paint. */

(function () {
  // ---- translations -----------------------------------------------------
  // English is the source language and the fallback for any missing key.
  var STRINGS = {
    en: {
      toggle_theme_to_dark: 'Dark theme',
      toggle_theme_to_light: 'Light theme',
      toggle_sheet: 'Collapse / expand panel',
      switch_language: 'Auf Deutsch wechseln',
      unknown: 'unknown',

      // index page
      app_title: 'FindMy Map',
      loading: 'Loading…',
      refresh: 'Refresh now',
      refreshing: 'Refreshing…',
      timeline_link: 'Timeline →',
      edit: 'Edit',
      last_poll: 'Last poll',
      never: 'none yet',
      error: 'Error',
      server_unreachable: 'Server unreachable',
      devices_without_location: '{n} device(s) without a current location',
      err_no_response: 'no response',
      err_fetch_failed: 'fetch failed',
      err_decryption_failed: 'decryption failed',
      err_no_location_data: 'no location data',
      err_no_location: 'no location',
      p_time: 'Time',
      p_accuracy: 'Accuracy',
      p_status: 'Status',
      p_own_report: 'Own report',
      yes: 'yes',
      no: 'no',
      f_name: 'Name',
      f_pin_color: 'Pin colour',
      save: 'Save',
      cancel: 'Cancel',
      reset_default: 'Default',

      // timeline page
      page_title_timeline: 'FindMy Map – Timeline',
      timeline_heading: 'Timeline',
      back_to_map: '← Back to map',
      f_device: 'Device',
      f_from: 'From',
      f_to: 'To',
      show: 'Show',
      loading_short: 'Loading…',
      visited_places: 'Visited places',
      no_devices: 'No devices found.',
      history_load_error: 'Failed to load the history.',
      no_points_in_range: 'No locations in the selected period.',
      locations_count: '{n} locations',
      start: 'Start',
      end: 'End',
      resolving_address: 'Resolving address…',
      geocoding_disabled: 'Address lookup disabled (GFM_NOMINATIM_URL is empty).',
      no_visits: 'No stays (at least 15 min in one place) in the selected period. '
        + 'Once more location data has accumulated, visited places will appear here.',
      unit_min: 'min',
      unit_hour: 'h',

      // login page
      page_title_login: 'FindMy Map – Sign in',
      login_heading: 'FindMy Map',
      f_password: 'Password',
      sign_in: 'Sign in',
      login_wrong: 'Wrong password.',
      login_throttled: 'Too many attempts — try again in {n} s.',
      login_error: 'Something went wrong. Try again.',

      // settings page
      settings: 'Settings',
      page_title_settings: 'FindMy Map – Settings',
      settings_heading: 'Settings',
      s_language: 'Language',
      s_theme: 'Theme',
      s_auth: 'Authentication',
      theme_light: 'Light',
      theme_dark: 'Dark',
      require_login: 'Require login',
      f_current_password: 'Current password',
      f_new_password: 'Password',
      f_new_password_optional: 'New password (leave blank to keep)',
      f_confirm_password: 'Confirm password',
      log_out: 'Log out',
      auth_saved_on: 'Saved. A login is now required.',
      auth_saved_off: 'Saved. Login is no longer required.',
      err_pw_short: 'Password must be at least 8 characters.',
      err_pw_mismatch: 'The passwords do not match.',
      err_current_pw: 'Current password is incorrect.',
    },
    de: {
      toggle_theme_to_dark: 'Dunkles Design',
      toggle_theme_to_light: 'Helles Design',
      toggle_sheet: 'Panel ein-/ausklappen',
      switch_language: 'Switch to English',
      unknown: 'unbekannt',

      app_title: 'FindMy Map',
      loading: 'Lade…',
      refresh: 'Jetzt aktualisieren',
      refreshing: 'Aktualisiere…',
      timeline_link: 'Zeitachse →',
      edit: 'Bearbeiten',
      last_poll: 'Letzte Abfrage',
      never: 'noch keine',
      error: 'Fehler',
      server_unreachable: 'Server nicht erreichbar',
      devices_without_location: '{n} Gerät(e) ohne aktuellen Standort',
      err_no_response: 'keine Antwort',
      err_fetch_failed: 'Abruf fehlgeschlagen',
      err_decryption_failed: 'Entschlüsselung fehlgeschlagen',
      err_no_location_data: 'keine Standortdaten',
      err_no_location: 'kein Standort',
      p_time: 'Zeit',
      p_accuracy: 'Genauigkeit',
      p_status: 'Status',
      p_own_report: 'Eigener Report',
      yes: 'ja',
      no: 'nein',
      f_name: 'Name',
      f_pin_color: 'Pin-Farbe',
      save: 'Speichern',
      cancel: 'Abbrechen',
      reset_default: 'Standard',

      page_title_timeline: 'FindMy Map – Zeitachse',
      timeline_heading: 'Zeitachse',
      back_to_map: '← Zurück zur Karte',
      f_device: 'Gerät',
      f_from: 'Von',
      f_to: 'Bis',
      show: 'Anzeigen',
      loading_short: 'Lädt…',
      visited_places: 'Besuchte Orte',
      no_devices: 'Keine Geräte gefunden.',
      history_load_error: 'Fehler beim Laden des Verlaufs.',
      no_points_in_range: 'Keine Standorte im gewählten Zeitraum.',
      locations_count: '{n} Standorte',
      start: 'Start',
      end: 'Ende',
      resolving_address: 'Adresse wird ermittelt…',
      geocoding_disabled: 'Adressen deaktiviert (GFM_NOMINATIM_URL leer).',
      no_visits: 'Keine Aufenthalte (mind. 15 Min am selben Ort) im gewählten Zeitraum. '
        + 'Sobald sich mehr Standortdaten angesammelt haben, erscheinen hier die besuchten Orte.',
      unit_min: 'Min',
      unit_hour: 'Std',

      // login page
      page_title_login: 'FindMy Map – Anmelden',
      login_heading: 'FindMy Map',
      f_password: 'Passwort',
      sign_in: 'Anmelden',
      login_wrong: 'Falsches Passwort.',
      login_throttled: 'Zu viele Versuche — in {n} s erneut probieren.',
      login_error: 'Etwas ist schiefgelaufen. Bitte erneut versuchen.',

      // settings page
      settings: 'Einstellungen',
      page_title_settings: 'FindMy Map – Einstellungen',
      settings_heading: 'Einstellungen',
      s_language: 'Sprache',
      s_theme: 'Design',
      s_auth: 'Authentifizierung',
      theme_light: 'Hell',
      theme_dark: 'Dunkel',
      require_login: 'Login erforderlich',
      f_current_password: 'Aktuelles Passwort',
      f_new_password: 'Passwort',
      f_new_password_optional: 'Neues Passwort (leer lassen zum Behalten)',
      f_confirm_password: 'Passwort bestätigen',
      log_out: 'Abmelden',
      auth_saved_on: 'Gespeichert. Ein Login ist jetzt erforderlich.',
      auth_saved_off: 'Gespeichert. Kein Login mehr erforderlich.',
      err_pw_short: 'Das Passwort muss mindestens 8 Zeichen haben.',
      err_pw_mismatch: 'Die Passwörter stimmen nicht überein.',
      err_current_pw: 'Aktuelles Passwort ist falsch.',
    },
  };

  function readLang() {
    try {
      var v = localStorage.getItem('lang');
      if (v === 'en' || v === 'de') return v;
    } catch (e) {}
    return 'en';
  }

  var lang = readLang();

  function t(key, vars) {
    var s = (STRINGS[lang] && STRINGS[lang][key]) || STRINGS.en[key] || key;
    if (vars) {
      for (var k in vars) s = s.replace('{' + k + '}', vars[k]);
    }
    return s;
  }

  function locale() { return lang === 'de' ? 'de-DE' : 'en-GB'; }

  function applyStaticI18n() {
    document.querySelectorAll('[data-i18n]').forEach(function (el) {
      el.textContent = t(el.getAttribute('data-i18n'));
    });
    document.querySelectorAll('[data-i18n-aria]').forEach(function (el) {
      el.setAttribute('aria-label', t(el.getAttribute('data-i18n-aria')));
    });
    var titleEl = document.querySelector('title[data-i18n]');
    if (titleEl) document.title = t(titleEl.getAttribute('data-i18n'));
  }

  // ---- theme ----------------------------------------------------------
  try {
    var savedTheme = localStorage.getItem('theme');
    if (savedTheme === 'light' || savedTheme === 'dark') {
      document.documentElement.dataset.theme = savedTheme;
    }
  } catch (e) {}

  function currentTheme() {
    return document.documentElement.dataset.theme === 'light' ? 'light' : 'dark';
  }

  function applyTheme(theme) {
    document.documentElement.dataset.theme = theme;
    try { localStorage.setItem('theme', theme); } catch (e) {}
    var btn = document.getElementById('theme-toggle');
    if (btn) {
      var clickGoesToDark = theme === 'light';
      btn.textContent = clickGoesToDark ? '☾' : '☀';
      btn.title = t(clickGoesToDark ? 'toggle_theme_to_dark' : 'toggle_theme_to_light');
      btn.setAttribute('aria-label', btn.title);
    }
  }

  // ---- language toggle -----------------------------------------------
  function applyLangToggle() {
    var btn = document.getElementById('lang-toggle');
    if (!btn) return;
    btn.textContent = lang.toUpperCase();
    btn.title = t('switch_language');
    btn.setAttribute('aria-label', btn.title);
  }

  function setLang(next) {
    lang = next;
    try { localStorage.setItem('lang', next); } catch (e) {}
    document.documentElement.lang = next;
    applyStaticI18n();
    applyLangToggle();
    applyTheme(currentTheme());  // refresh the theme tooltip in the new language
    if (typeof window.FindMyMap.onLangChange === 'function') {
      window.FindMyMap.onLangChange(next);
    }
  }

  // ---- public API + wiring ------------------------------------------
  window.FindMyMap = window.FindMyMap || {};
  window.FindMyMap.t = t;
  window.FindMyMap.locale = locale;
  window.FindMyMap.getLang = function () { return lang; };
  window.FindMyMap.onThemeChange = null;
  window.FindMyMap.onLangChange = null;

  document.documentElement.lang = lang;

  function setup() {
    applyStaticI18n();
    applyLangToggle();
    applyTheme(currentTheme());

    var themeBtn = document.getElementById('theme-toggle');
    if (themeBtn) themeBtn.addEventListener('click', function () {
      var next = currentTheme() === 'light' ? 'dark' : 'light';
      applyTheme(next);
      if (typeof window.FindMyMap.onThemeChange === 'function') {
        window.FindMyMap.onThemeChange(next);
      }
    });

    var langBtn = document.getElementById('lang-toggle');
    if (langBtn) langBtn.addEventListener('click', function () {
      setLang(lang === 'de' ? 'en' : 'de');
    });
  }

  if (document.readyState !== 'loading') setup();
  else document.addEventListener('DOMContentLoaded', setup);
})();
