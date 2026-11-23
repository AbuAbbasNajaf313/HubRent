// HubRent – Mail-Vorlagen für den Code-Node "Mail bauen" in WF-01 (Mail Dispatcher).
//
// Quelle für den Node: scripts/build_n8n_workflows.py bettet diese Datei ein.
// Eingang: Events von Flask (Webhook, Daten unter json.body) oder von WF-02/03/04
// (gleiches Format, plus "fee" und "links" aus der internen API).
// Ausgang pro Event ein Item: { send, event, to, subject, html, text, reservation_id, payload }.
// Events ohne Mail (z. B. strike.issued) bekommen send=false und werden nur protokolliert.

const BRAND = '#ea580c';
const DARK = '#1c1917';

function esc(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function euro(value) {
  const n = Number(value || 0);
  return n.toFixed(2).replace('.', ',') + ' €';
}

function button(href, label, color) {
  if (!href) return '';
  return `<a href="${esc(href)}" style="display:inline-block;background:${color || BRAND};color:#ffffff;` +
    `text-decoration:none;font-weight:600;padding:12px 20px;border-radius:8px;margin:4px 8px 4px 0">${esc(label)}</a>`;
}

function facts(d) {
  const r = d.reservation || {};
  const rows = [
    ['Gerät', d.device && d.device.name],
    ['Hub', d.hub && `${d.hub.name} · ${d.hub.address}`],
    ['Zeitraum', `${r.start_local} bis ${r.end_local}`],
    ['Preis', euro(r.price)],
    ['Code', r.code],
  ];
  return '<table style="border-collapse:collapse;font-size:14px;margin:16px 0">' +
    rows.map(([k, v]) => `<tr><td style="color:#78716c;padding:4px 16px 4px 0">${esc(k)}</td>` +
      `<td style="padding:4px 0">${esc(v)}</td></tr>`).join('') + '</table>';
}

function pinBox(d) {
  const r = d.reservation || {};
  return `<div style="background:${DARK};color:#ffffff;border-radius:12px;padding:20px;margin:16px 0">` +
    `<div style="font-size:12px;color:#a8a29e;text-transform:uppercase">Deine PIN</div>` +
    `<div style="font-family:monospace;font-size:32px;font-weight:700;letter-spacing:6px">${esc(r.pin)}</div>` +
    `<div style="margin-top:8px;font-size:14px">Fach ${esc(d.device && d.device.locker_number)} · ` +
    `abholbar ${esc(r.pickup_from_local)} bis ${esc(r.pickup_until_local)}</div></div>`;
}

function strikeLine(d) {
  return `<p style="font-size:13px;color:#78716c">Dein Strike-Stand: ${esc(d.customer && d.customer.strike_text)}</p>`;
}

function layout(heading, inner) {
  return '<!doctype html><html lang="de"><body style="margin:0;background:#f5f5f4;font-family:Arial,Helvetica,sans-serif;color:' + DARK + '">' +
    '<div style="max-width:560px;margin:0 auto;padding:24px">' +
    `<div style="font-weight:700;font-size:18px;margin-bottom:16px"><span style="background:${BRAND};color:#fff;border-radius:6px;padding:4px 8px;margin-right:8px">HR</span>HubRent</div>` +
    '<div style="background:#ffffff;border-radius:12px;padding:24px;border:1px solid #e7e5e4">' +
    `<h1 style="font-size:22px;margin:0 0 12px">${esc(heading)}</h1>${inner}</div>` +
    '<p style="font-size:11px;color:#a8a29e;margin-top:16px">HubRent ist ein fiktives Demo-Projekt. Diese Mail wurde automatisch verschickt.</p>' +
    '</div></body></html>';
}

function feeOf(d) {
  if (d.fee && d.fee.amount !== undefined) return Number(d.fee.amount);
  if (d.extra && d.extra.fee !== undefined) return Number(d.extra.fee);
  return 0;
}

// Jede Vorlage liefert Betreff, Überschrift, HTML-Inhalt und Klartext (Fallback für einfache Mailprogramme).
const TEMPLATES = {
  'reservation.created': (d) => ({
    subject: `Reservierung eingegangen: ${d.device.name} (${d.reservation.code})`,
    heading: 'Deine Reservierung ist eingegangen',
    html: `<p>Hallo ${esc(d.customer.full_name)},</p><p>wir haben deine Reservierung erhalten. Zwei Tage vor Mietbeginn ` +
      'fragen wir per Mail nach, ob es dabei bleibt. Du kannst auch jetzt schon bestätigen.</p>' + facts(d) +
      button(d.links && d.links.confirm, 'Jetzt bestätigen') + button(d.links && d.links.cancel, 'Stornieren', '#78716c'),
    text: `Hallo ${d.customer.full_name}, deine Reservierung ${d.reservation.code} (${d.device.name}, ` +
      `${d.reservation.start_local} bis ${d.reservation.end_local}) ist eingegangen.\n` +
      `Bestätigen: ${(d.links && d.links.confirm) || '-'}\nStornieren: ${(d.links && d.links.cancel) || '-'}`,
  }),

  'reservation.reminder': (d) => ({
    subject: `Bitte bestätige deine Reservierung (${d.reservation.code})`,
    heading: 'Bleibt es bei deiner Reservierung?',
    html: `<p>Hallo ${esc(d.customer.full_name)},</p><p>bitte bestätige deine Reservierung, damit wir das Gerät für dich ` +
      'bereithalten. Ohne Bestätigung geben wir es 24 Stunden vor Beginn kostenlos wieder frei.</p>' + facts(d) +
      button(d.links && d.links.confirm, 'Ja, ich hole es ab') + button(d.links && d.links.cancel, 'Stornieren (kostenlos)', '#78716c'),
    text: `Hallo ${d.customer.full_name}, bitte bestätige deine Reservierung ${d.reservation.code}.\n` +
      `Bestätigen: ${d.links && d.links.confirm}\nStornieren: ${d.links && d.links.cancel}`,
  }),

  'reservation.confirmed': (d) => ({
    subject: `Deine PIN für ${d.device.name}: ${d.reservation.pin}`,
    heading: 'Bestätigt! Hier ist deine PIN.',
    html: `<p>Hallo ${esc(d.customer.full_name)},</p><p>deine Reservierung ist verbindlich. Gib die PIN am Terminal im Hub ein, ` +
      'dann öffnet sich dein Fach.</p>' + pinBox(d) + facts(d) + strikeLine(d),
    text: `Hallo ${d.customer.full_name}, deine PIN: ${d.reservation.pin}, Fach ${d.device.locker_number}, ` +
      `${d.hub.name} (${d.hub.address}). Abholung ${d.reservation.pickup_from_local} bis ${d.reservation.pickup_until_local}.\n` +
      `Strike-Stand: ${d.customer.strike_text}`,
  }),

  'reservation.auto_cancelled': (d) => ({
    subject: `Reservierung freigegeben (${d.reservation.code})`,
    heading: 'Deine Reservierung wurde freigegeben',
    html: `<p>Hallo ${esc(d.customer.full_name)},</p><p>du hast die Reservierung nicht rechtzeitig bestätigt. Wir haben das ` +
      'Gerät deshalb freigegeben. Das ist kostenlos und gibt keinen Strike.</p>' + facts(d),
    text: `Hallo ${d.customer.full_name}, deine Reservierung ${d.reservation.code} wurde mangels Bestätigung kostenlos freigegeben.`,
  }),

  'reservation.cancelled': (d) => {
    const free = !d.extra || d.extra.free_of_charge !== false;
    const fee = feeOf(d);
    const note = free ? 'Die Stornierung war kostenlos.'
      : `Da die Stornierung weniger als 24 Stunden vor Mietbeginn kam, gibt es einen Strike${fee > 0 ? ` und eine Gebühr von ${euro(fee)}` : ' (Verwarnung, keine Gebühr)'}.`;
    return {
      subject: `Storniert: ${d.device.name} (${d.reservation.code})`,
      heading: 'Deine Reservierung ist storniert',
      html: `<p>Hallo ${esc(d.customer.full_name)},</p><p>${esc(note)}</p>` + facts(d) + (free ? '' : strikeLine(d)),
      text: `Hallo ${d.customer.full_name}, deine Reservierung ${d.reservation.code} ist storniert. ${note}`,
    };
  },

  'reservation.no_show': (d) => {
    const fee = feeOf(d);
    const note = fee > 0 ? `Dafür gibt es einen Strike und eine Gebühr von ${euro(fee)}.` : 'Dafür gibt es einen Strike (Verwarnung, noch keine Gebühr).';
    return {
      subject: `Nicht abgeholt: ${d.device.name} (${d.reservation.code})`,
      heading: 'Du hast deine Reservierung nicht abgeholt',
      html: `<p>Hallo ${esc(d.customer.full_name)},</p><p>das Abholfenster ist abgelaufen und das Gerät stand umsonst bereit. ` +
        `${esc(note)}</p>` + facts(d) + strikeLine(d) +
        '<p style="font-size:13px">Tipp: Mit 5 pünktlichen Mieten in Folge baust du einen Strike wieder ab.</p>',
      text: `Hallo ${d.customer.full_name}, Reservierung ${d.reservation.code} wurde nicht abgeholt. ${note}\n` +
        `Strike-Stand: ${d.customer.strike_text}`,
    };
  },

  'reservation.returned': (d) => {
    const onTime = !d.extra || d.extra.on_time !== false;
    return {
      subject: `Danke für die Rückgabe (${d.reservation.code})`,
      heading: 'Danke, Gerät ist zurück!',
      html: `<p>Hallo ${esc(d.customer.full_name)},</p><p>${onTime ? 'Pünktlich zurückgegeben, danke!' : 'Die Rückgabe kam verspätet, deine Serie sauberer Mieten beginnt neu.'}</p>` +
        facts(d) + strikeLine(d),
      text: `Hallo ${d.customer.full_name}, danke für die Rückgabe von ${d.device.name}. Strike-Stand: ${d.customer.strike_text}`,
    };
  },

  'strike.reduced': (d) => ({
    subject: 'Ein Strike weniger',
    heading: 'Gut gemacht: ein Strike weniger',
    html: `<p>Hallo ${esc(d.customer.full_name)},</p><p>fünf saubere Mieten in Folge, dafür haben wir einen Strike abgebaut.</p>` + strikeLine(d),
    text: `Hallo ${d.customer.full_name}, nach fünf sauberen Mieten ist ein Strike weg. Stand: ${d.customer.strike_text}`,
  }),
};

const out = [];
for (const item of $input.all()) {
  const d = item.json.body || item.json;
  const template = TEMPLATES[d.event];
  const base = { event: d.event, reservation_id: (d.reservation && d.reservation.id) || '', payload: d };
  if (!template || !d.customer || !d.customer.email) {
    out.push({ json: { ...base, send: false } });
    continue;
  }
  const mail = template(d);
  out.push({
    json: { ...base, send: true, to: d.customer.email, subject: mail.subject, html: layout(mail.heading, mail.html), text: mail.text },
  });
}
return out;
