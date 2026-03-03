// ══════════════════════════════════════════════════════════════════
// GESTIONPRO - JAVASCRIPT PRINCIPAL
// Versión 2.0 con Calendario Global de Admins, Chats Mejorados y Adjuntos
// ══════════════════════════════════════════════════════════════════

// ══════════════════════════════════════════
//  DATA
// ══════════════════════════════════════════

let USERS = [
  {
    id: 1,
    username: "antonio",
    password: "admin123",
    name: "Antonio",
    role: "admin",
    email: "antonio@rodonverges.com",
    phone: "+34 93 000 00 01",
    active: true,
  },
  {
    id: 2,
    username: "myriam",
    password: "myriam123",
    name: "Myriam",
    role: "empleado",
    email: "myriam@rodonverges.com",
    phone: "+34 93 000 00 02",
    active: true,
    departamento: "laboral",
  },
  {
    id: 3,
    username: "sara",
    password: "sara123",
    name: "Sara",
    role: "empleado",
    email: "sara@rodonverges.com",
    phone: "+34 93 000 00 03",
    active: true,
    departamento: "fiscal",
  },
];

let SERVICES = [
  {
    id: 1,
    name: "Asesoramiento Fiscal",
    desc: "Optimización fiscal y cumplimiento normativo para particulares y empresas.",
  },
  {
    id: 2,
    name: "Gestión Laboral",
    desc: "Nóminas, contratos, altas y bajas en la Seguridad Social.",
  },
  {
    id: 3,
    name: "Contabilidad",
    desc: "Contabilidad general, balances y cuentas de resultados.",
  },
  {
    id: 4,
    name: "Auditoría",
    desc: "Revisión independiente de estados financieros y procesos internos.",
  },
  {
    id: 5,
    name: "Consultoría Empresarial",
    desc: "Estrategia, organización y mejora de procesos de negocio.",
  },
  {
    id: 6,
    name: "Asesoramiento Jurídico",
    desc: "Apoyo legal en contratos mercantiles y disputas empresariales.",
  },
];

let EVENTS = [
  {
    id: 1,
    ownerId: 1,
    assignedTo: 1,
    date: dOff(0),
    time: "09:00",
    client: "Carlos Martínez",
    service: "Asesoramiento Fiscal",
    notes: "Revisión declaración anual",
    private: false,
  },
  {
    id: 2,
    ownerId: 1,
    assignedTo: 2,
    date: dOff(1),
    time: "11:00",
    client: "Laura Gómez",
    service: "Gestión Laboral",
    notes: "Alta nuevo trabajador",
    private: false,
  },
  {
    id: 3,
    ownerId: 1,
    assignedTo: 3,
    date: dOff(2),
    time: "16:00",
    client: "Inversions Sud SA",
    service: "Auditoría",
    notes: "Primera reunión",
    private: false,
  },
  {
    id: 4,
    ownerId: 2,
    assignedTo: 2,
    date: dOff(3),
    time: "10:30",
    client: "Ana Rodríguez",
    service: "Contabilidad",
    notes: "Cierre trimestral",
    private: false,
  },
  {
    id: 5,
    ownerId: 1,
    assignedTo: 1,
    date: dOff(1),
    time: "15:00",
    client: "Consultes Privades SL",
    service: "Asesoramiento Jurídico",
    notes: "Reunión confidencial de dirección",
    private: true,
  },
];

let CONVS = {};
let GROUPS = [];

const DEPARTAMENTOS = ['laboral', 'fiscal', 'mercantil'];

let DEPT_PERMISSIONS = {
  laboral:   { level: 2, accessToDepts: [] },
  fiscal:    { level: 2, accessToDepts: [] },
  mercantil: { level: 2, accessToDepts: [] },
};

let deptCalMonth = {
  laboral:   new Date(),
  fiscal:    new Date(),
  mercantil: new Date(),
};

let adminCalMonth = new Date();

(function () {
  function seed(a, b, msgs) {
    const key = [a, b].sort((x, y) => x - y).join("-");
    CONVS[key] = msgs;
  }
  seed(1, 2, [
    {
      mine: false,
      text: "Buenos días, ¿has podido revisar el informe de Carlos?",
      time: "09:15",
      read: true,
      attachment: null,
    },
    {
      mine: true,
      text: "Sí, acabo de enviarlo por email al cliente.",
      time: "09:22",
      read: true,
      attachment: null,
    },
    {
      mine: false,
      text: "Perfecto, lo reviso ahora mismo.",
      time: "10:24",
      read: false,
      attachment: null,
    },
  ]);
})();

let GENERAL_CHAT = [
  {
    id: 1,
    userId: 1,
    text: "Buenos días a todos. Recordad que hoy tenemos reunión de equipo a las 10h.",
    time: "08:45",
    date: dOff(0),
  },
  {
    id: 2,
    userId: 2,
    text: "Anotado, gracias por el aviso!",
    time: "08:52",
    date: dOff(0),
  },
];
let nextGchatId = 100;

// ══════════════════════════════════════════
//  APP STATE
// ══════════════════════════════════════════

let nextEventId = 100;
let nextUserId = 100;
let nextServiceId = 100;
let nextGroupId = 100;
let currentUser = null;
let myCalMonth = new Date();
let globalCalMonth = new Date();
let activeConvId = null;
let editingEvId = null;
let editingUserId = null;
let editingSrvId = null;
let pendingIsGlobal = false;
let currentDetailId = null;
let gchatUnreadCount = 0;
let pendingFileAttachment = null;

// ══════════════════════════════════════════
//  UTILS
// ══════════════════════════════════════════

function dOff(d) {
  const x = new Date();
  x.setDate(x.getDate() + d);
  return x.toISOString().split("T")[0];
}

function todayStr() {
  return new Date().toISOString().split("T")[0];
}

function fmtDate(s) {
  if (!s) return "";
  const d = new Date(s + "T00:00:00");
  return d.toLocaleDateString("es-ES", {
    day: "numeric",
    month: "long",
    year: "numeric",
  });
}

function fmtDateShort(s) {
  if (!s) return "";
  const d = new Date(s + "T00:00:00");
  return d.toLocaleDateString("es-ES", { day: "numeric", month: "long" });
}

function mthName(d) {
  const n = d.toLocaleDateString("es-ES", {
    month: "long",
    year: "numeric",
  });
  return n.charAt(0).toUpperCase() + n.slice(1);
}

function initials(name) {
  return name
    .split(" ")
    .map((w) => w[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();
}

function greet() {
  const h = new Date().getHours();
  return h < 12
    ? "Buenos días"
    : h < 19
      ? "Buenas tardes"
      : "Buenas noches";
}

function nowTime() {
  return new Date().toLocaleTimeString("es-ES", {
    hour: "2-digit",
    minute: "2-digit",
  });
}

function convKey(a, b) {
  return [a, b].sort((x, y) => x - y).join("-");
}

function convData(otherId) {
  const k = convKey(currentUser.id, otherId);
  if (!CONVS[k]) CONVS[k] = [];
  return CONVS[k];
}

function unreadOf(otherId) {
  return convData(otherId).filter((m) => !m.mine && !m.read).length;
}

function totalUnread() {
  return USERS.filter((u) => u.id !== currentUser.id).reduce(
    (s, u) => s + unreadOf(u.id),
    0,
  );
}

function safeHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function updateBadge() {
  const n = totalUnread();
  const b = document.getElementById("msg-badge");
  if (b) {
    b.textContent = n;
    b.style.display = n > 0 ? "" : "none";
  }
  const g = document.getElementById("gchat-badge");
  if (g) {
    g.textContent = gchatUnreadCount;
    g.style.display = gchatUnreadCount > 0 ? "" : "none";
  }
}

function getAdminUsers() {
  return USERS.filter(u => u.role === 'admin' && u.active);
}

// ══════════════════════════════════════════
//  AUTH
// ══════════════════════════════════════════

function doLogin() {
  const u = document.getElementById("login-user").value.trim();
  const p = document.getElementById("login-pass").value;
  const found = USERS.find(
    (x) => x.username === u && x.password === p && x.active,
  );
  if (!found) {
    document.getElementById("login-error").style.display = "block";
    return;
  }
  document.getElementById("login-error").style.display = "none";
  currentUser = found;
  document.getElementById("login-screen").style.display = "none";
  document.getElementById("app").style.display = "flex";
  initApp();
}

function doLogout() {
  currentUser = null;
  activeConvId = null;
  editingEvId = null;
  gchatUnreadCount = 0;
  pendingFileAttachment = null;
  document.getElementById("app").style.display = "none";
  document.getElementById("login-screen").style.display = "flex";
  document.getElementById("login-user").value = "";
  document.getElementById("login-pass").value = "";
  document.querySelector(".sidebar").classList.remove("open");
  document.getElementById("sidebar-overlay").classList.remove("active");
}

function toggleSidebar() {
  const sidebar = document.querySelector(".sidebar");
  const overlay = document.getElementById("sidebar-overlay");
  sidebar.classList.toggle("open");
  overlay.classList.toggle("active");
}

document.getElementById("login-pass").addEventListener("keydown", (e) => {
  if (e.key === "Enter") doLogin();
});

// ══════════════════════════════════════════
//  INIT
// ══════════════════════════════════════════

function initApp() {
  const isAdmin = currentUser.role === "admin";
  document.getElementById("sidebar-avatar").textContent = initials(
    currentUser.name,
  );
  document.getElementById("sidebar-name").textContent = currentUser.name;
  document.getElementById("sidebar-role").textContent = isAdmin
    ? "Administrador"
    : "Empleado";
  const greetingEl = document.getElementById("topbar-greeting");
  greetingEl.textContent = "Hola, " + currentUser.name.split(" ")[0] + "!";
  greetingEl.style.display = "block";
  document.getElementById("topbar-date").textContent =
    new Date().toLocaleDateString("es-ES", {
      weekday: "long",
      day: "numeric",
      month: "long",
    });
  document
    .querySelectorAll(".admin-only")
    .forEach((el) => (el.style.display = isAdmin ? "" : "none"));
  gchatUnreadCount = 0;
  updateBadge();
  updateDeptCalNav();
  populateNewChatUsers();
  showSection("dashboard");
}

// ══════════════════════════════════════════
//  NAVIGATION
// ══════════════════════════════════════════

const SEC_TITLES = {
  dashboard: "Inicio",
  "my-calendar": "Mi Calendario",
  "admin-calendars-global": "Calendario de Administradores",
  "global-calendar": "Calendario Global",
  "cal-laboral": "Calendario Laboral",
  "cal-fiscal": "Calendario Fiscal",
  "cal-mercantil": "Calendario Mercantil",
  "admin-manage": "Administración",
  users: "Gestión de Usuarios",
  services: "Servicios",
  "general-chat": "Chat General",
  messages: "Mensajería",
};

function showSection(name) {
  if (window.innerWidth <= 768) {
    document.querySelector(".sidebar").classList.remove("open");
    document.getElementById("sidebar-overlay").classList.remove("active");
  }
  document
    .querySelectorAll(".section")
    .forEach((s) => s.classList.remove("active"));
  document
    .querySelectorAll(".nav-item")
    .forEach((n) => n.classList.remove("active"));
  const el = document.getElementById("section-" + name);
  if (el) el.classList.add("active");
  const ni = document.querySelector('.nav-item[data-sec="' + name + '"]');
  if (ni) ni.classList.add("active");
  document.getElementById("topbar-title").textContent = SEC_TITLES[name] || name;

  if (name === "dashboard") renderDashboard();
  if (name === "my-calendar") renderCalendar("my");
  if (name === "admin-calendars-global") { populateAdminFilter(); renderAdminCalendar(); }
  if (name === "global-calendar") { populateGlobalFilter(); renderCalendar("global"); }
  if (name === "cal-laboral") renderDeptCalendar("laboral");
  if (name === "cal-fiscal") renderDeptCalendar("fiscal");
  if (name === "cal-mercantil") renderDeptCalendar("mercantil");
  if (name === "admin-manage") renderPermissionsPanel();
  if (name === "users") renderUsers();
  if (name === "services") renderServices();
  if (name === "general-chat") openGeneralChat();
  if (name === "messages") renderMessages();
}

// ══════════════════════════════════════════
//  DASHBOARD
// ══════════════════════════════════════════

function renderDashboard() {
  const isAdmin = currentUser.role === "admin";
  const today = todayStr();
  const myEvs = EVENTS.filter((e) => e.assignedTo === currentUser.id);
  const todayEvs = myEvs.filter((e) => e.date === today);

  const stats = isAdmin
    ? [
        {
          label: "Citas hoy",
          value: todayEvs.length,
          sub: "Total del día",
          cls: "",
        },
        {
          label: "Citas total",
          value: EVENTS.length,
          sub: "Programadas",
          cls: "green",
        },
        {
          label: "Empleados",
          value: USERS.filter((u) => u.active).length,
          sub: "Activos",
          cls: "amber",
        },
        {
          label: "Servicios",
          value: SERVICES.length,
          sub: "Disponibles",
          cls: "",
        },
      ]
    : [
        {
          label: "Citas hoy",
          value: todayEvs.length,
          sub: "Tus citas de hoy",
          cls: "",
        },
        {
          label: "Citas mes",
          value: myEvs.filter((e) => e.date.startsWith(today.slice(0, 7)))
            .length,
          sub: "Este mes",
          cls: "green",
        },
        {
          label: "Total citas",
          value: myEvs.length,
          sub: "Programadas",
          cls: "amber",
        },
        {
          label: "Clientes",
          value: [...new Set(myEvs.map((e) => e.client))].length,
          sub: "Únicos",
          cls: "",
        },
      ];

  document.getElementById("stats-grid").innerHTML = stats
    .map(
      (s) => `
    <div class="stat-card ${s.cls}">
      <div class="stat-label">${s.label}</div>
      <div class="stat-value">${s.value}</div>
      <div class="stat-sub">${s.sub}</div>
    </div>`,
    )
    .join("");

  document.getElementById("dash-greeting").textContent =
    greet() + ", " + currentUser.name + "!";
  document.getElementById("dash-sub").textContent =
    "Resumen de actividad · " + fmtDate(today);

  const upcoming = myEvs
    .filter((e) => e.date >= today)
    .sort((a, b) =>
      a.date === b.date
        ? a.time.localeCompare(b.time)
        : a.date.localeCompare(b.date),
    )
    .slice(0, 6);
  const dotCls = ["", "amber", "red"];
  document.getElementById("upcoming-events").innerHTML = upcoming.length
    ? upcoming
        .map((ev, i) => {
          const emp = USERS.find((u) => u.id === ev.assignedTo);
          return `<div class="task-item">
      <div class="t-dot ${dotCls[i % 3]}"></div>
      <div style="flex:1">
        <div class="t-title">${safeHtml(ev.client)}</div>
        <div class="t-meta">${fmtDate(ev.date)} &middot; ${ev.time} &middot; ${safeHtml(ev.service)}${isAdmin && emp ? " &middot; <strong>" + safeHtml(emp.name) + "</strong>" : ""}</div>
      </div>
      <span class="tag tag-gray" style="white-space:nowrap">${ev.time}</span>
    </div>`;
        })
        .join("")
    : '<div style="color:var(--text-muted);font-size:13px;padding:8px 0">Sin citas pendientes.</div>';

  document.getElementById("recent-activity").innerHTML = `
    <div class="task-item"><div class="t-dot"></div><div><div class="t-title">Sesión iniciada</div><div class="t-meta">Hace unos momentos</div></div></div>
    <div class="task-item"><div class="t-dot amber"></div><div><div class="t-title">Chat General disponible</div><div class="t-meta">${GENERAL_CHAT.length} mensajes en el canal</div></div></div>
    <div class="task-item"><div class="t-dot red"></div><div><div class="t-title">${EVENTS.length} citas en el sistema</div><div class="t-meta">Actualizado ahora</div></div></div>`;
}

// ══════════════════════════════════════════
//  CALENDARIOS
// ══════════════════════════════════════════

function changeMonth(dir, which) {
  if (which === "my") {
    myCalMonth = new Date(myCalMonth.getFullYear(), myCalMonth.getMonth() + dir, 1);
    renderCalendar("my");
  } else {
    globalCalMonth = new Date(globalCalMonth.getFullYear(), globalCalMonth.getMonth() + dir, 1);
    renderCalendar("global");
  }
}

function changeAdminMonth(dir) {
  adminCalMonth = new Date(adminCalMonth.getFullYear(), adminCalMonth.getMonth() + dir, 1);
  renderAdminCalendar();
}

function changeDeptMonth(dir, dept) {
  deptCalMonth[dept] = new Date(deptCalMonth[dept].getFullYear(), deptCalMonth[dept].getMonth() + dir, 1);
  renderDeptCalendar(dept);
}

function populateAdminFilter() {
  const sel = document.getElementById("admin-filter-person");
  if (!sel) return;
  const admins = getAdminUsers();
  sel.innerHTML = '<option value="all">Todos los admins</option>' +
    admins.map(u => `<option value="${u.id}">${safeHtml(u.name)}</option>`).join('');
}

function renderAdminCalendar() {
  const date = adminCalMonth;
  const isAdmin = currentUser.role === "admin";

  document.getElementById("admin-cal-title").textContent = mthName(date);

  const year = date.getFullYear(), month = date.getMonth();
  const daysInMonth = new Date(year, month + 1, 0).getDate();
  let dow = new Date(year, month, 1).getDay();
  dow = dow === 0 ? 6 : dow - 1;
  const monthStr = `${year}-${String(month + 1).padStart(2, "0")}`;

  const admins = getAdminUsers();
  const adminIds = admins.map(u => u.id);

  let evs = EVENTS.filter(e => e.date.startsWith(monthStr) && adminIds.includes(e.assignedTo));

  const personFilter = document.getElementById("admin-filter-person");
  if (personFilter && personFilter.value && personFilter.value !== "all") {
    const filterId = parseInt(personFilter.value);
    evs = evs.filter(e => e.assignedTo === filterId);
  }

  const deptFilter = document.getElementById("admin-filter-dept");
  if (deptFilter && deptFilter.value && deptFilter.value !== "all") {
    const selectedDept = deptFilter.value;
    evs = evs.filter(e => {
      const assignedUser = USERS.find(u => u.id === e.assignedTo);
      return assignedUser && assignedUser.departamento === selectedDept;
    });
  }

  if (!isAdmin) {
    evs = evs.filter(e => !e.private);
  }

  const today = todayStr();
  const colors = ["", "amber", "red"];
  let html = "";

  const calCellsEl = document.getElementById("admin-cal-cells");
  if (!calCellsEl) return;

  for (let i = 0; i < dow; i++) html += '<div class="cal-cell empty"></div>';

  for (let day = 1; day <= daysInMonth; day++) {
    const ds = `${year}-${String(month + 1).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
    const isToday = ds === today;
    const dayEvs = evs.filter(e => e.date === ds);

    const evHTML = dayEvs.slice(0, 3).map((ev, i) => {
      const emp = USERS.find(u => u.id === ev.assignedTo);
      const empName = emp ? emp.name.split(' ')[0] : '?';
      if (ev.private && !isAdmin) {
        return `<div class="cell-event blocked-private" title="Horario no disponible" onclick="event.stopPropagation()">🔒 ${ev.time}</div>`;
      }
      return `<div class="cell-event ${colors[i % 3]}${ev.private ? ' private-event' : ''}" onclick="showEventDetail(${ev.id},event)">${ev.private ? '🔒 ' : ''}${ev.time} ${empName}</div>`;
    }).join("");

    html += `<div class="cal-cell${isToday ? " today" : ""}" onclick="calCellClick('${ds}',event,'admin')">
      <div class="cell-num">${day}</div>${evHTML}
      ${dayEvs.length > 3 ? `<div style="font-size:10px;color:var(--text-muted);padding:1px 4px">+${dayEvs.length - 3}</div>` : ""}
    </div>`;
  }

  const totalCells = dow + daysInMonth;
  for (let i = totalCells; i < 42; i++) html += '<div class="cal-cell empty"></div>';

  calCellsEl.innerHTML = html;
  renderAdminApptList(evs);
}

function renderAdminApptList(evs) {
  const listEl = document.getElementById("admin-appt-list");
  if (!listEl) return;
  const isAdmin = currentUser.role === "admin";
  const sorted = evs.slice().sort((a, b) =>
    a.date === b.date ? a.time.localeCompare(b.time) : a.date.localeCompare(b.date)
  );
  if (!sorted.length) {
    listEl.innerHTML = '<div style="padding:20px;text-align:center;color:var(--text-muted);font-size:13px">No hay citas este mes</div>';
    return;
  }
  listEl.innerHTML = sorted.map(ev => {
    const emp = USERS.find(u => u.id === ev.assignedTo);
    const shouldMask = ev.private && !isAdmin;
    if (shouldMask) {
      return `<div class="appt-item blocked">
        <div class="appt-time-col"><strong>${ev.time}</strong><span>${ev.date}</span></div>
        <div class="appt-info">
          <div class="appt-client">🔒 Tarea privatizada</div>
          <div class="appt-meta">Horario no disponible</div>
        </div>
      </div>`;
    }
    const canEdit = isAdmin || ev.ownerId === currentUser.id;
    const privBtn = isAdmin ? `<button class="btn-icon" title="${ev.private ? 'Hacer pública' : 'Privatizar'}" onclick="toggleEventPrivacy(${ev.id},event)">${ev.private ? '🔓' : '🔒'}</button>` : '';
    return `<div class="appt-item">
      <div class="appt-time-col"><strong>${ev.time}</strong><span>${ev.date}</span></div>
      <div class="appt-info">
        <div class="appt-client">${safeHtml(ev.client)}${ev.private ? ' <span class="private-badge">🔒 Privado</span>' : ''}</div>
        <div class="appt-meta">${safeHtml(ev.service)}</div>
        ${emp ? `<div class="appt-admin">👤 ${safeHtml(emp.name)}</div>` : ''}
      </div>
      <div class="action-btns">
        ${canEdit ? `${privBtn}<button class="btn-icon" onclick="editEventFromList(${ev.id},event)">Editar</button><button class="btn-icon red" onclick="deleteEventFromList(${ev.id},event)">Eliminar</button>` : ''}
      </div>
    </div>`;
  }).join("");
}

function renderCalendar(which) {
  const isMy = which === "my";
  const date = isMy ? myCalMonth : globalCalMonth;
  const isAdmin = currentUser.role === "admin";

  if (!(date instanceof Date) || isNaN(date.getTime())) {
    console.error("Invalid calendar date:", date);
    return;
  }

  document.getElementById(
    isMy ? "my-cal-title" : "global-cal-title",
  ).textContent = mthName(date);

  const year = date.getFullYear(), month = date.getMonth();
  const daysInMonth = new Date(year, month + 1, 0).getDate();
  let dow = new Date(year, month, 1).getDay();
  dow = dow === 0 ? 6 : dow - 1;

  const monthStr = `${year}-${String(month + 1).padStart(2, "0")}`;
  let evs = EVENTS.filter((e) => e.date.startsWith(monthStr));

  if (isMy) {
    evs = evs.filter((e) => e.assignedTo === currentUser.id);
  } else {
    if (!isAdmin) {
      evs = evs.filter((e) => {
        if (!e.private) return true;
        return e.assignedTo === currentUser.id;
      });
    }
    const filterSel = document.getElementById("global-filter-person");
    if (filterSel && filterSel.value && filterSel.value !== "all") {
      const filterId = parseInt(filterSel.value);
      evs = evs.filter((e) => e.assignedTo === filterId);
    }
  }

  const today = todayStr();
  const colors = ["", "amber", "red"];
  let html = "";

  const calCellsEl = document.getElementById(
    isMy ? "my-cal-cells" : "global-cal-cells",
  );
  if (!calCellsEl) return;

  for (let i = 0; i < dow; i++)
    html += '<div class="cal-cell empty"></div>';

  for (let day = 1; day <= daysInMonth; day++) {
    const ds = `${year}-${String(month + 1).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
    const isToday = ds === today;
    const dayEvs = evs.filter((e) => e.date === ds);

    const evHTML = dayEvs
      .slice(0, 3)
      .map((ev, i) => {
        const shouldMask = ev.private && !isAdmin && ev.assignedTo !== currentUser.id;
        if (shouldMask) {
          return `<div class="cell-event blocked-private" title="Horario no disponible" onclick="event.stopPropagation()">🔒 ${ev.time}</div>`;
        }
        return `<div class="cell-event ${colors[i % 3]}${ev.private ? ' private-event' : ''}" onclick="showEventDetail(${ev.id},event)">${ev.private ? '🔒 ' : ''}${ev.time} ${safeHtml(ev.client)}</div>`;
      })
      .join("");

    html += `<div class="cal-cell${isToday ? " today" : ""}" onclick="calCellClick('${ds}',event,'${which}')">
      <div class="cell-num">${day}</div>${evHTML}
      ${dayEvs.length > 3 ? `<div style="font-size:10px;color:var(--text-muted);padding:1px 4px">+${dayEvs.length - 3} más</div>` : ""}
    </div>`;
  }

  const totalCells = dow + daysInMonth;
  for (let i = totalCells; i < 42; i++)
    html += '<div class="cal-cell empty"></div>';

  calCellsEl.innerHTML = html;

  renderApptList(
    which,
    evs.filter((e) => e.date.startsWith(monthStr)),
  );
}

function renderApptList(which, evs) {
  const listId = which === "my" ? "my-appt-list" : "global-appt-list";
  const el = document.getElementById(listId);
  if (!el) return;
  const isAdmin = currentUser.role === "admin";
  const visibleEvs = evs;
  const sorted = visibleEvs
    .slice()
    .sort((a, b) =>
      a.date === b.date
        ? a.time.localeCompare(b.time)
        : a.date.localeCompare(b.date),
    );
  if (!sorted.length) {
    el.innerHTML =
      '<div style="padding:20px;text-align:center;color:var(--text-muted);font-size:13px">No hay citas este mes</div>';
    return;
  }
  el.innerHTML = sorted
    .map((ev) => {
      const emp = USERS.find((u) => u.id === ev.assignedTo);
      const canEdit =
        isAdmin ||
        ev.assignedTo === currentUser.id ||
        ev.ownerId === currentUser.id;
      const privBtn = isAdmin
        ? `<button class="btn-icon" title="${ev.private ? 'Hacer pública' : 'Privatizar'}" onclick="toggleEventPrivacy(${ev.id},event)">${ev.private ? '🔓' : '🔒'}</button>`
        : '';

      const shouldMask = ev.private && !isAdmin && ev.assignedTo !== currentUser.id;
      if (shouldMask) {
        return `<div class="appt-item blocked">
      <div class="appt-time-col"><strong>${ev.time}</strong><span>${ev.date}</span></div>
      <div class="appt-info">
        <div class="appt-client">🔒 Tarea privatizada</div>
        <div class="appt-meta">Horario no disponible</div>
      </div>
    </div>`;
      }

      return `<div class="appt-item">
      <div class="appt-time-col"><strong>${ev.time}</strong><span>${ev.date}</span></div>
      <div class="appt-info">
        <div class="appt-client">${safeHtml(ev.client)}${ev.private ? ' <span class="private-badge">🔒 Privado</span>' : ''}</div>
        <div class="appt-meta">${safeHtml(ev.service)}${emp && (isAdmin || which === 'global') ? " &middot; <strong>" + safeHtml(emp.name) + "</strong>" : ""}</div>
      </div>
      <div class="action-btns">
        ${canEdit ? `
          ${privBtn}
          <button class="btn-icon" title="Editar" onclick="editEventFromList(${ev.id},event)">Editar</button>
          <button class="btn-icon red" title="Eliminar" onclick="deleteEventFromList(${ev.id},event)">Eliminar</button>
        ` : ''}
      </div>
    </div>`;
    })
    .join("");
}

function calCellClick(ds, e, which) {
  if (e.target.classList.contains("cell-event")) return;
  openEventModal(which === "global" || which === "admin", ds);
}

function showEventDetail(evId, e) {
  if (e) e.stopPropagation();
  const ev = EVENTS.find((x) => x.id === evId);
  if (!ev) return;

  const isAdmin = currentUser.role === "admin";
  if (ev.private && !isAdmin && ev.assignedTo !== currentUser.id) {
    return;
  }

  currentDetailId = evId;
  const emp = USERS.find((u) => u.id === ev.assignedTo);
  const canEdit =
    isAdmin ||
    ev.ownerId === currentUser.id ||
    ev.assignedTo === currentUser.id;
  document.getElementById("detail-title").textContent = ev.client;
  const isPrivate = ev.private;
  document.getElementById("detail-body").innerHTML =
    `<div style="display:grid;gap:14px">
  ${isPrivate ? `<div><span class="private-badge">🔒 Cita privada</span></div>` : ""}
  <div><span style="font-size:11px;text-transform:uppercase;letter-spacing:1px;color:var(--text-muted)">Fecha y hora</span><br>${fmtDate(ev.date)} a las ${ev.time}</div>
  <div><span style="font-size:11px;text-transform:uppercase;letter-spacing:1px;color:var(--text-muted)">Servicio</span><br>${safeHtml(ev.service)}</div>
  ${emp ? `<div><span style="font-size:11px;text-transform:uppercase;letter-spacing:1px;color:var(--text-muted)">Empleado asignado</span><br>${safeHtml(emp.name)}</div>` : ""}
  <div><span style="font-size:11px;text-transform:uppercase;letter-spacing:1px;color:var(--text-muted)">Notas</span><br>${safeHtml(ev.notes) || "—"}</div>
</div>`;
  document.getElementById("det-del-btn").style.display = canEdit ? "" : "none";
  document.getElementById("det-edit-btn").style.display = canEdit ? "" : "none";
  const privBtn = document.getElementById("det-privacy-btn");
  if (privBtn) {
    privBtn.style.display = isAdmin ? "" : "none";
    privBtn.textContent = ev.private ? "🔓 Hacer pública" : "🔒 Privatizar";
  }
  openModal("detail-modal");
}

function deleteCurrentEvent() {
  if (currentDetailId === null) return;
  EVENTS = EVENTS.filter((e) => e.id !== currentDetailId);
  currentDetailId = null;
  closeModal("detail-modal");
  refreshCals();
  renderDashboard();
}

function editCurrentEvent() {
  const ev = EVENTS.find((x) => x.id === currentDetailId);
  if (!ev) return;
  closeModal("detail-modal");
  openEditEvent(ev);
}

function editEventFromList(evId, e) {
  if (e) e.stopPropagation();
  const ev = EVENTS.find((x) => x.id === evId);
  if (ev) openEditEvent(ev);
}

function deleteEventFromList(evId, e) {
  if (e) e.stopPropagation();
  if (!confirm("¿Eliminar esta cita?")) return;
  EVENTS = EVENTS.filter((x) => x.id !== evId);
  refreshCals();
  renderDashboard();
}

function toggleEventPrivacy(evId, e) {
  if (e) e.stopPropagation();
  if (currentUser.role !== "admin") return;
  const ev = EVENTS.find((x) => x.id === evId);
  if (!ev) return;
  ev.private = !ev.private;
  refreshCals();
  renderDashboard();
}

function toggleCurrentEventPrivacy() {
  if (currentUser.role !== "admin" || currentDetailId === null) return;
  const ev = EVENTS.find((x) => x.id === currentDetailId);
  if (!ev) return;
  ev.private = !ev.private;
  const privBtn = document.getElementById("det-privacy-btn");
  if (privBtn) privBtn.textContent = ev.private ? "🔓 Hacer pública" : "🔒 Privatizar";
  const badge = document.querySelector("#detail-body .private-badge");
  if (ev.private && !badge) {
    const firstDiv = document.querySelector("#detail-body > div > div:first-child");
    if (firstDiv) firstDiv.insertAdjacentHTML("beforebegin", '<div><span class="private-badge">🔒 Cita privada</span></div>');
  } else if (!ev.private && badge) {
    badge.closest("div").remove();
  }
  refreshCals();
  renderDashboard();
}

// ══════════════════════════════════════════
//  MODAL EVENTOS
// ══════════════════════════════════════════

function fillServiceSelect() {
  const sel = document.getElementById("ev-service");
  sel.innerHTML = SERVICES.map(
    (s) =>
      `<option value="${safeHtml(s.name)}">${safeHtml(s.name)}</option>`,
  ).join("");
}

function fillEmployeeSelect(selectedId) {
  const grp = document.getElementById("ev-employee-group");
  const isAdmin = currentUser.role === "admin";
  grp.style.display = (isAdmin && pendingIsGlobal) ? "" : "none";
  if (isAdmin) {
    document.getElementById("ev-employee").innerHTML = USERS.filter(
      (u) => u.active,
    )
      .map(
        (u) =>
          `<option value="${u.id}"${u.id === selectedId ? " selected" : ""}>${safeHtml(u.name)}</option>`,
      )
      .join("");
  }
}

function openEventModal(isGlobal, dateStr) {
  editingEvId = null;
  pendingIsGlobal = isGlobal;
  document.getElementById("event-modal-title").textContent = isGlobal
    ? "Agendar cita"
    : "Nueva cita";
  document.getElementById("event-modal-sub").textContent = isGlobal
    ? "Asigna una cita a un empleado"
    : "Añade una nueva cita a tu calendario";
  document.getElementById("ev-save-btn").textContent = "Guardar cita";
  document.getElementById("ev-date").value = dateStr || todayStr();
  document.getElementById("ev-time").value = "09:00";
  document.getElementById("ev-client").value = "";
  document.getElementById("ev-notes").value = "";
  document.getElementById("ev-err").style.display = "none";
  const pvGroup = document.getElementById("ev-private-group");
  if (pvGroup) pvGroup.style.display = currentUser.role === "admin" ? "flex" : "none";
  const pvChk = document.getElementById("ev-private");
  if (pvChk) pvChk.checked = false;
  fillServiceSelect();
  fillEmployeeSelect(currentUser.id);
  openModal("event-modal");
}

function openEditEvent(ev) {
  editingEvId = ev.id;
  pendingIsGlobal = currentUser.role === "admin";
  document.getElementById("event-modal-title").textContent =
    "Editar cita";
  document.getElementById("event-modal-sub").textContent =
    "Modifica los datos de la cita";
  document.getElementById("ev-save-btn").textContent = "Guardar cambios";
  document.getElementById("ev-date").value = ev.date;
  document.getElementById("ev-time").value = ev.time;
  document.getElementById("ev-client").value = ev.client;
  document.getElementById("ev-notes").value = ev.notes || "";
  document.getElementById("ev-err").style.display = "none";
  const pvGroup = document.getElementById("ev-private-group");
  if (pvGroup) pvGroup.style.display = currentUser.role === "admin" ? "flex" : "none";
  const pvChk = document.getElementById("ev-private");
  if (pvChk) pvChk.checked = !!ev.private;
  fillServiceSelect();
  document.getElementById("ev-service").value = ev.service;
  fillEmployeeSelect(ev.assignedTo);
  openModal("event-modal");
}

function saveEvent() {
  const date = document.getElementById("ev-date").value;
  const time = document.getElementById("ev-time").value;
  const client = document.getElementById("ev-client").value.trim();
  if (!date || !time || !client) {
    document.getElementById("ev-err").style.display = "";
    return;
  }
  document.getElementById("ev-err").style.display = "none";
  const isAdmin = currentUser.role === "admin";
  const assignedTo = (isAdmin && pendingIsGlobal)
    ? parseInt(document.getElementById("ev-employee").value)
    : currentUser.id;
  const service = document.getElementById("ev-service").value;
  const notes = document.getElementById("ev-notes").value;
  const isPrivate = isAdmin ? (document.getElementById("ev-private")?.checked || false) : false;
  if (editingEvId !== null) {
    const ev = EVENTS.find((e) => e.id === editingEvId);
    if (ev) {
      ev.date = date;
      ev.time = time;
      ev.client = client;
      ev.service = service;
      ev.notes = notes;
      if (isAdmin) { ev.assignedTo = assignedTo; ev.private = isPrivate; }
    }
  } else {
    EVENTS.push({
      id: nextEventId++,
      ownerId: currentUser.id,
      assignedTo,
      date,
      time,
      client,
      service,
      notes,
      private: isPrivate,
    });
  }
  closeModal("event-modal");
  refreshCals();
  renderDashboard();
}

function populateGlobalFilter() {
  const sel = document.getElementById("global-filter-person");
  if (!sel) return;
  const current = sel.value;
  sel.innerHTML = '<option value="all">Todos</option>' +
    USERS.filter(u => u.active).map(u =>
      `<option value="${u.id}"${String(u.id) === current ? ' selected' : ''}>${safeHtml(u.name)}</option>`
    ).join('');
}

function refreshCals() {
  try {
    const myCalSection = document.getElementById("section-my-calendar");
    const globalCalSection = document.getElementById("section-global-calendar");
    const adminCalSection = document.getElementById("section-admin-calendars-global");
    if (myCalSection && myCalSection.classList.contains("active")) renderCalendar("my");
    if (globalCalSection && globalCalSection.classList.contains("active")) renderCalendar("global");
    if (adminCalSection && adminCalSection.classList.contains("active")) renderAdminCalendar();
    DEPARTAMENTOS.forEach(dept => {
      const sec = document.getElementById("section-cal-" + dept);
      if (sec && sec.classList.contains("active")) renderDeptCalendar(dept);
    });
  } catch (e) {
    console.error("Error refreshing calendars:", e);
  }
}

// ══════════════════════════════════════════
//  DEPARTAMENT CALENDARS
// ══════════════════════════════════════════

function canAccessDeptCalendar(dept) {
  const isAdmin = currentUser.role === "admin";
  if (isAdmin) return true;
  const userDept = currentUser.departamento;
  if (!userDept) return false;
  const perm = DEPT_PERMISSIONS[userDept];
  if (!perm) return false;
  if (perm.level === 1) return false;
  if (perm.level === 2) return dept === userDept;
  if (perm.level === 3) return dept === userDept || perm.accessToDepts.includes(dept);
  return false;
}

function renderDeptCalendar(dept) {
  if (!canAccessDeptCalendar(dept)) {
    showSection('my-calendar');
    return;
  }
  const date = deptCalMonth[dept];
  const titleEl = document.getElementById("dept-" + dept + "-cal-title");
  const cellsEl = document.getElementById("dept-" + dept + "-cal-cells");
  if (!titleEl || !cellsEl) return;

  titleEl.textContent = mthName(date);
  const year = date.getFullYear(), month = date.getMonth();
  const daysInMonth = new Date(year, month + 1, 0).getDate();
  let dow = new Date(year, month, 1).getDay();
  dow = dow === 0 ? 6 : dow - 1;
  const monthStr = `${year}-${String(month + 1).padStart(2, "0")}`;

  const deptUsers = USERS.filter(u => u.departamento === dept && u.active);
  const deptUserIds = deptUsers.map(u => u.id);

  let evs = EVENTS.filter(e => e.date.startsWith(monthStr) && deptUserIds.includes(e.assignedTo));
  if (currentUser.role !== "admin") {
    evs = evs.filter(e => !e.private || e.assignedTo === currentUser.id);
  }

  const today = todayStr();
  const colors = ["", "amber", "red"];
  let html = "";
  for (let i = 0; i < dow; i++) html += '<div class="cal-cell empty"></div>';
  for (let day = 1; day <= daysInMonth; day++) {
    const ds = `${year}-${String(month + 1).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
    const isToday = ds === today;
    const dayEvs = evs.filter(e => e.date === ds);
    const evHTML = dayEvs.slice(0, 3).map((ev, i) => {
      const shouldMask = ev.private && currentUser.role !== 'admin' && ev.assignedTo !== currentUser.id;
      if (shouldMask) {
        return `<div class="cell-event blocked-private" title="Horario no disponible" onclick="event.stopPropagation()">🔒 ${ev.time}</div>`;
      }
      return `<div class="cell-event ${colors[i % 3]}${ev.private ? ' private-event' : ''}" onclick="showEventDetail(${ev.id},event)">${ev.private ? '🔒 ' : ''}${ev.time} ${safeHtml(ev.client)}</div>`;
    }).join("");
    html += `<div class="cal-cell${isToday ? " today" : ""}" onclick="calCellClick('${ds}',event,'dept-${dept}')">
      <div class="cell-num">${day}</div>${evHTML}
      ${dayEvs.length > 3 ? `<div style="font-size:10px;color:var(--text-muted);padding:1px 4px">+${dayEvs.length - 3} más</div>` : ""}
    </div>`;
  }
  const totalCells = dow + daysInMonth;
  for (let i = totalCells; i < 42; i++) html += '<div class="cal-cell empty"></div>';
  cellsEl.innerHTML = html;

  const listEl = document.getElementById("dept-" + dept + "-appt-list");
  if (!listEl) return;
  const sorted = evs.slice().sort((a, b) => a.date === b.date ? a.time.localeCompare(b.time) : a.date.localeCompare(b.date));
  if (!sorted.length) {
    listEl.innerHTML = '<div style="padding:20px;text-align:center;color:var(--text-muted);font-size:13px">No hay citas este mes en el departamento</div>';
    return;
  }
  const isAdmin = currentUser.role === "admin";
  listEl.innerHTML = sorted.map(ev => {
    const shouldMask = ev.private && !isAdmin && ev.assignedTo !== currentUser.id;
    if (shouldMask) {
      return `<div class="appt-item blocked">
        <div class="appt-time-col"><strong>${ev.time}</strong><span>${ev.date}</span></div>
        <div class="appt-info">
          <div class="appt-client">🔒 Tarea privatizada</div>
          <div class="appt-meta">Horario no disponible</div>
        </div>
      </div>`;
    }
    const emp = USERS.find(u => u.id === ev.assignedTo);
    const canEdit = isAdmin || ev.assignedTo === currentUser.id || ev.ownerId === currentUser.id;
    const privBtn = isAdmin ? `<button class="btn-icon" title="${ev.private ? 'Hacer pública' : 'Privatizar'}" onclick="toggleEventPrivacy(${ev.id},event)">${ev.private ? '🔓' : '🔒'}</button>` : '';
    return `<div class="appt-item">
      <div class="appt-time-col"><strong>${ev.time}</strong><span>${ev.date}</span></div>
      <div class="appt-info">
        <div class="appt-client">${safeHtml(ev.client)}${ev.private ? ' <span class="private-badge">🔒 Privado</span>' : ''}</div>
        <div class="appt-meta">${safeHtml(ev.service)}${emp ? ' &middot; <strong>' + safeHtml(emp.name) + '</strong>' : ''}</div>
      </div>
      <div class="action-btns">
        ${canEdit ? `${privBtn}<button class="btn-icon" onclick="editEventFromList(${ev.id},event)">Editar</button><button class="btn-icon red" onclick="deleteEventFromList(${ev.id},event)">Eliminar</button>` : ''}
      </div>
    </div>`;
  }).join("");
}

// ══════════════════════════════════════════
//  PERMISSIONS
// ══════════════════════════════════════════

function renderPermissionsPanel() {
  const el = document.getElementById("permissions-panel");
  if (!el || currentUser.role !== "admin") return;
  el.innerHTML = DEPARTAMENTOS.map(dept => {
    const perm = DEPT_PERMISSIONS[dept];
    const deptLabel = dept.charAt(0).toUpperCase() + dept.slice(1);
    const otherDepts = DEPARTAMENTOS.filter(d => d !== dept);
    const deptChecks = otherDepts.map(d => {
      const checked = perm.accessToDepts.includes(d) ? "checked" : "";
      return `<label><input type="checkbox" ${checked} onchange="updateDeptAccess('${dept}','${d}',this.checked)" />${d.charAt(0).toUpperCase() + d.slice(1)}</label>`;
    }).join("");
    return `<div class="perm-dept-block">
      <div class="perm-dept-title">
        <span class="tag tag-dept-${dept}">${deptLabel}</span>
        Departamento ${deptLabel}
      </div>
      <div class="perm-radio-group">
        <label class="perm-radio-label">
          <input type="radio" name="perm-${dept}" value="1" ${perm.level === 1 ? 'checked' : ''} onchange="setDeptPermLevel('${dept}',1)" />
          <div><div>Solo calendario personal</div><div class="perm-radio-desc">El empleado solo ve sus propias citas</div></div>
        </label>
        <label class="perm-radio-label">
          <input type="radio" name="perm-${dept}" value="2" ${perm.level === 2 ? 'checked' : ''} onchange="setDeptPermLevel('${dept}',2)" />
          <div><div>Ver calendario de departamento</div><div class="perm-radio-desc">Ve las citas de todos sus compañeros de departamento</div></div>
        </label>
        <label class="perm-radio-label">
          <input type="radio" name="perm-${dept}" value="3" ${perm.level === 3 ? 'checked' : ''} onchange="setDeptPermLevel('${dept}',3)" />
          <div><div>Acceso a otros calendarios</div><div class="perm-radio-desc">Además de su departamento, puede acceder a otros departamentos seleccionados</div></div>
        </label>
      </div>
      <div class="perm-dept-access" id="perm-access-${dept}" style="${perm.level === 3 ? '' : 'display:none'}">
        <div style="font-size:12px;font-weight:500;color:var(--text-muted);margin-bottom:8px;text-transform:uppercase;letter-spacing:0.8px">Departamentos accesibles:</div>
        ${deptChecks}
      </div>
    </div>`;
  }).join("");
}

function setDeptPermLevel(dept, level) {
  if (currentUser.role !== "admin") return;
  DEPT_PERMISSIONS[dept].level = parseInt(level);
  if (level < 3) DEPT_PERMISSIONS[dept].accessToDepts = [];
  const accessEl = document.getElementById("perm-access-" + dept);
  if (accessEl) accessEl.style.display = level == 3 ? "" : "none";
  updateDeptCalNav();
}

function updateDeptAccess(dept, targetDept, checked) {
  if (currentUser.role !== "admin") return;
  if (checked) {
    if (!DEPT_PERMISSIONS[dept].accessToDepts.includes(targetDept))
      DEPT_PERMISSIONS[dept].accessToDepts.push(targetDept);
  } else {
    DEPT_PERMISSIONS[dept].accessToDepts = DEPT_PERMISSIONS[dept].accessToDepts.filter(d => d !== targetDept);
  }
  updateDeptCalNav();
}

function updateDeptCalNav() {
  const isAdmin = currentUser.role === "admin";
  document.querySelectorAll(".dept-cal-nav").forEach(el => {
    const dept = el.getAttribute("data-dept");
    el.style.display = canAccessDeptCalendar(dept) ? "" : "none";
  });
}

// ══════════════════════════════════════════
//  USUARIOS
// ══════════════════════════════════════════

function renderUsers() {
  document.getElementById("user-count").textContent =
    USERS.filter((u) => u.active).length + " usuarios activos";
  document.getElementById("users-table-body").innerHTML = USERS.map(
    (u) => {
      const deptTag = u.role !== "admin" && u.departamento
        ? `<span class="tag tag-dept-${u.departamento}" style="text-transform:capitalize">${u.departamento}</span>`
        : `<span class="tag tag-dept-none">—</span>`;
      return `
  <tr>
    <td><div class="user-cell"><div class="mini-avatar">${initials(u.name)}</div><div><div style="font-weight:500">${safeHtml(u.name)}</div><div style="font-size:12px;color:var(--text-muted)">@${safeHtml(u.username)}</div></div></div></td>
    <td><span class="tag ${u.role === "admin" ? "tag-blue" : "tag-green"}">${u.role === "admin" ? "Admin" : "Empleado"}</span></td>
    <td>${deptTag}</td>
    <td style="color:var(--text-muted)">${safeHtml(u.email || "—")}</td>
    <td style="color:var(--text-muted)">${safeHtml(u.phone || "—")}</td>
    <td><span class="tag ${u.active ? "tag-green" : "tag-gray"}">${u.active ? "Activo" : "Inactivo"}</span></td>
    <td>
      <div class="action-btns">
        <button class="btn-icon" title="Editar" onclick="editUser(${u.id})">Editar</button>
        <button class="btn-icon red" title="${u.active ? "Desactivar" : "Activar"}" onclick="toggleUser(${u.id})">${u.active ? "Desactivar" : "Activar"}</button>
      </div>
    </td>
  </tr>`;
    }
  ).join("");
}

function openUserModal() {
  editingUserId = null;
  document.getElementById("user-modal-title").textContent = "Nuevo usuario";
  document.getElementById("nu-save-btn").textContent = "Crear usuario";
  ["nu-name", "nu-user", "nu-pass", "nu-email", "nu-phone"].forEach(
    (id) => (document.getElementById(id).value = ""),
  );
  document.getElementById("nu-role").selectedIndex = 0;
  document.getElementById("nu-dept").selectedIndex = 0;
  document.getElementById("nu-err").style.display = "none";
  document.getElementById("nu-dept-group").style.display = "";
  openModal("user-modal");
}

document.getElementById("nu-role").addEventListener("change", function() {
  document.getElementById("nu-dept-group").style.display = this.value === "admin" ? "none" : "";
});

function editUser(id) {
  const u = USERS.find((x) => x.id === id);
  if (!u) return;
  editingUserId = id;
  document.getElementById("user-modal-title").textContent = "Editar usuario";
  document.getElementById("nu-save-btn").textContent = "Guardar cambios";
  document.getElementById("nu-name").value = u.name;
  document.getElementById("nu-user").value = u.username;
  document.getElementById("nu-pass").value = "";
  document.getElementById("nu-email").value = u.email || "";
  document.getElementById("nu-phone").value = u.phone || "";
  document.getElementById("nu-role").value = u.role;
  const deptGroup = document.getElementById("nu-dept-group");
  if (u.role === "admin") {
    deptGroup.style.display = "none";
  } else {
    deptGroup.style.display = "";
    document.getElementById("nu-dept").value = u.departamento || "laboral";
  }
  document.getElementById("nu-err").style.display = "none";
  openModal("user-modal");
}

function saveUser() {
  const name = document.getElementById("nu-name").value.trim();
  const uname = document.getElementById("nu-user").value.trim();
  const pass = document.getElementById("nu-pass").value;
  const email = document.getElementById("nu-email").value.trim();
  const phone = document.getElementById("nu-phone").value.trim();
  const role = document.getElementById("nu-role").value;
  const dept = role !== "admin" ? document.getElementById("nu-dept").value : null;
  const errEl = document.getElementById("nu-err");

  if (!name || !uname) {
    errEl.textContent = "Nombre y usuario son obligatorios.";
    errEl.style.display = "";
    return;
  }
  if (editingUserId === null && !pass) {
    errEl.textContent = "La contraseña es obligatoria.";
    errEl.style.display = "";
    return;
  }
  if (role !== "admin" && !dept) {
    errEl.textContent = "El departamento es obligatorio para empleados.";
    errEl.style.display = "";
    return;
  }
  const dupUser = USERS.find(
    (u) => u.username === uname && u.id !== editingUserId,
  );
  if (dupUser) {
    errEl.textContent = "El nombre de usuario ya existe.";
    errEl.style.display = "";
    return;
  }
  errEl.style.display = "none";

  if (editingUserId !== null) {
    const u = USERS.find((x) => x.id === editingUserId);
    if (u) {
      u.name = name;
      u.username = uname;
      u.email = email;
      u.phone = phone;
      u.role = role;
      u.departamento = role !== "admin" ? dept : null;
      if (pass) u.password = pass;
    }
  } else {
    USERS.push({
      id: nextUserId++,
      username: uname,
      password: pass,
      name,
      role,
      departamento: role !== "admin" ? dept : null,
      email,
      phone,
      active: true,
    });
  }
  closeModal("user-modal");
  renderUsers();
  buildMsgList();
  updateGchatHeader();
  updateDeptCalNav();
  populateNewChatUsers();
}

function toggleUser(id) {
  if (id === currentUser.id) {
    alert("No puedes desactivar tu propio usuario.");
    return;
  }
  const u = USERS.find((x) => x.id === id);
  if (u) u.active = !u.active;
  renderUsers();
  populateNewChatUsers();
}

// ══════════════════════════════════════════
//  SERVICIOS
// ══════════════════════════════════════════

function renderServices() {
  const isAdmin = currentUser.role === "admin";
  if (!SERVICES.length) {
    document.getElementById("services-list").innerHTML =
      '<div style="padding:24px;text-align:center;color:var(--text-muted);font-size:13px">No hay servicios registrados.</div>';
    return;
  }
  document.getElementById("services-list").innerHTML = SERVICES.map(
    (s, idx) => `
  <div class="srv-item">
    <div class="srv-num">${String(idx + 1).padStart(2, "0")}</div>
    <div class="srv-info">
      <div class="srv-name">${safeHtml(s.name)}</div>
      <div class="srv-desc">${safeHtml(s.desc || "")}</div>
    </div>
    ${
      isAdmin
        ? `
      <div class="action-btns">
        <button class="btn-icon" title="Editar" onclick="editService(${s.id})">Editar</button>
        <button class="btn-icon red" title="Eliminar" onclick="deleteService(${s.id})">Eliminar</button>
      </div>`
        : ""
    }
  </div>`,
  ).join("");
}

function openServiceModal() {
  editingSrvId = null;
  document.getElementById("srv-modal-title").textContent =
    "Nuevo servicio";
  document.getElementById("srv-save-btn").textContent = "Guardar";
  document.getElementById("srv-name").value = "";
  document.getElementById("srv-desc").value = "";
  document.getElementById("srv-err").style.display = "none";
  openModal("service-modal");
}

function editService(id) {
  const s = SERVICES.find((x) => x.id === id);
  if (!s) return;
  editingSrvId = id;
  document.getElementById("srv-modal-title").textContent =
    "Editar servicio";
  document.getElementById("srv-save-btn").textContent = "Guardar cambios";
  document.getElementById("srv-name").value = s.name;
  document.getElementById("srv-desc").value = s.desc || "";
  document.getElementById("srv-err").style.display = "none";
  openModal("service-modal");
}

function saveService() {
  const name = document.getElementById("srv-name").value.trim();
  const desc = document.getElementById("srv-desc").value.trim();
  const errEl = document.getElementById("srv-err");
  if (!name) {
    errEl.style.display = "";
    return;
  }
  errEl.style.display = "none";
  if (editingSrvId !== null) {
    const s = SERVICES.find((x) => x.id === editingSrvId);
    if (s) {
      s.name = name;
      s.desc = desc;
    }
  } else {
    SERVICES.push({ id: nextServiceId++, name, desc });
  }
  closeModal("service-modal");
  renderServices();
}

function deleteService(id) {
  if (!confirm("¿Eliminar este servicio?")) return;
  SERVICES = SERVICES.filter((s) => s.id !== id);
  renderServices();
}

// ══════════════════════════════════════════
//  CHAT GENERAL
// ══════════════════════════════════════════

function updateGchatHeader() {
  const activeCount = USERS.filter((u) => u.active).length;
  const el = document.getElementById("gchat-online-count");
  if (el)
    el.textContent =
      activeCount +
      " miembro" +
      (activeCount !== 1 ? "s" : "") +
      " en el equipo";
  const lbl = document.getElementById("gchat-members-label");
  if (lbl)
    lbl.textContent =
      "Canal compartido · " + activeCount + " participantes";
}

function openGeneralChat() {
  gchatUnreadCount = 0;
  updateBadge();
  updateGchatHeader();
  renderGeneralChat();
  setTimeout(() => {
    document.getElementById("gchat-input").focus();
  }, 50);
}

function renderGeneralChat() {
  const el = document.getElementById("gchat-messages");
  if (!el) return;
  if (!GENERAL_CHAT.length) {
    el.innerHTML =
      '<div style="text-align:center;color:var(--text-muted);font-size:13px;padding:40px 0">No hay mensajes aún. ¡Sé el primero en escribir!</div>';
    return;
  }

  let html = "";
  let lastDate = null;
  let lastUserId = null;

  GENERAL_CHAT.forEach((msg) => {
    const sender = USERS.find((u) => u.id === msg.userId);
    const senderName = sender ? sender.name : "Usuario";
    const isMe = msg.userId === currentUser.id;
    const msgDate = msg.date;

    if (msgDate !== lastDate) {
      const today = todayStr();
      let label;
      if (msgDate === today) label = "Hoy";
      else if (msgDate === dOff(-1)) label = "Ayer";
      else label = fmtDateShort(msgDate);
      html += `<div class="gchat-day-sep"><span>${label}</span></div>`;
      lastDate = msgDate;
      lastUserId = null;
    }

    const showMeta = lastUserId !== msg.userId;
    lastUserId = msg.userId;

    html += `<div class="gchat-msg-group ${isMe ? "me" : ""}">`;
    if (showMeta) {
      html += `<div class="gchat-msg-meta ${isMe ? "me" : ""}">
    <div class="gchat-uavatar ${isMe ? "me" : ""}">${initials(senderName)}</div>
    <span class="gchat-sender">${isMe ? "Tú" : safeHtml(senderName)}</span>
  </div>`;
    }
    html += `<div class="gchat-bubble">${safeHtml(msg.text)}</div>
  <div class="gchat-time">${msg.time}</div>
  </div>`;
  });

  el.innerHTML = html;
  el.scrollTop = el.scrollHeight;
}

function gchatKeydown(e) {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    sendGchatMsg();
  }
}

function sendGchatMsg() {
  const inp = document.getElementById("gchat-input");
  const text = inp.value.trim();
  if (!text || !currentUser) return;
  GENERAL_CHAT.push({
    id: nextGchatId++,
    userId: currentUser.id,
    text,
    time: nowTime(),
    date: todayStr(),
  });
  inp.value = "";
  renderGeneralChat();
}

// ══════════════════════════════════════════
//  MENSAJERIA PRIVADA
// ══════════════════════════════════════════

function renderMessages() {
  buildMsgList();
  if (activeConvId !== null) openConv(activeConvId);
}

function buildMsgList(filter) {
  const others = USERS.filter((u) => u.id !== currentUser.id && u.active);
  const filtered = filter
    ? others.filter(
        (u) =>
          u.name.toLowerCase().includes(filter.toLowerCase()) ||
          u.username.toLowerCase().includes(filter.toLowerCase()),
      )
    : others;

  document.getElementById("msg-list").innerHTML = filtered
    .map((u) => {
      const msgs = convData(u.id);
      const last = msgs.length ? msgs[msgs.length - 1] : null;
      const unread = unreadOf(u.id);
      return `<div class="msg-conv ${activeConvId === u.id ? "active" : ""}" onclick="openConv(${u.id})">
    <div class="s-avatar" style="width:34px;height:34px;background:var(--accent-light);color:var(--accent);font-size:12px;flex-shrink:0">${initials(u.name)}</div>
    <div class="msg-conv-info">
      <div class="msg-conv-name">${safeHtml(u.name)}</div>
      <div class="msg-conv-preview">${last ? (last.mine ? "Tú: " : "") + (last.attachment ? "📎 Archivo" : safeHtml(last.text)) : "Inicia una conversación"}</div>
    </div>
    <div style="display:flex;flex-direction:column;align-items:flex-end;gap:4px">
      ${last ? `<div class="msg-conv-time">${last.time}</div>` : ""}
      ${unread > 0 ? `<div class="nav-badge">${unread}</div>` : ""}
    </div>
  </div>`;
    })
    .join("");
}

function filterConvs() {
  buildMsgList(document.getElementById("msg-search-inp").value);
}

function openConv(otherId) {
  activeConvId = otherId;
  const other = USERS.find((u) => u.id === otherId);
  if (!other) return;
  convData(otherId).forEach((m) => {
    if (!m.mine) m.read = true;
  });
  updateBadge();
  buildMsgList(document.getElementById("msg-search-inp").value);
  document.getElementById("msg-empty-state").style.display = "none";
  const chat = document.getElementById("msg-active-chat");
  chat.style.display = "flex";
  document.getElementById("chat-avatar").textContent = initials(
    other.name,
  );
  document.getElementById("chat-name").textContent = other.name;
  renderMsgs(otherId);
  document.getElementById("msg-input").focus();
  pendingFileAttachment = null;
}

function renderMsgs(otherId) {
  const msgs = convData(otherId);
  const el = document.getElementById("msg-messages");
  el.innerHTML = msgs.length
    ? msgs
        .map(
          (m) => {
            if (m.attachment) {
              return `<div class="msg-bubble-wrap ${m.mine ? "me" : ""}">
        <div class="msg-attachment">
          <span class="msg-attachment-icon">📎</span>
          <span class="msg-attachment-name">${safeHtml(m.attachment.name)}</span>
        </div>
        <div class="msg-time-label">${m.time}</div>
      </div>`;
            }
            return `<div class="msg-bubble-wrap ${m.mine ? "me" : ""}">
        <div class="msg-bubble">${safeHtml(m.text)}</div>
        <div class="msg-time-label">${m.time}</div>
      </div>`;
          }
        )
        .join("")
    : '<div style="text-align:center;color:var(--text-muted);font-size:13px;margin:auto">Inicia la conversación</div>';
  el.scrollTop = el.scrollHeight;
}

function msgKeydown(e) {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    sendMsg();
  }
}

function handleFileAttachment(event) {
  const file = event.target.files[0];
  if (!file) return;
  
  const maxSize = 5 * 1024 * 1024; // 5MB
  if (file.size > maxSize) {
    alert("El archivo no puede exceder 5MB");
    return;
  }
  
  pendingFileAttachment = {
    name: file.name,
    size: file.size,
    type: file.type,
  };
  
  // Show file info in the UI
  const reader = new FileReader();
  reader.onload = function(e) {
    pendingFileAttachment.data = e.target.result;
  };
  reader.readAsDataURL(file);
  
  event.target.value = '';
}

function sendMsg() {
  if (activeConvId === null) return;
  const inp = document.getElementById("msg-input");
  const text = inp.value.trim();
  
  if (!text && !pendingFileAttachment) return;
  
  const time = nowTime();
  const msg = {
    mine: true,
    time,
    read: true,
    attachment: null,
  };
  
  if (text) msg.text = text;
  if (pendingFileAttachment) msg.attachment = { name: pendingFileAttachment.name };
  
  convData(activeConvId).push(msg);
  inp.value = "";
  pendingFileAttachment = null;
  renderMsgs(activeConvId);
  buildMsgList(document.getElementById("msg-search-inp").value);
}

function populateNewChatUsers() {
  const sel = document.getElementById("new-chat-user");
  if (!sel) return;
  sel.innerHTML = '<option value="">-- Selecciona un usuario --</option>' +
    USERS.filter(u => u.id !== currentUser.id && u.active)
      .map(u => `<option value="${u.id}">${safeHtml(u.name)}</option>`)
      .join('');
}

function openNewChatModal() {
  document.getElementById("new-chat-err").style.display = "none";
  document.getElementById("new-chat-user").value = "";
  openModal("new-chat-modal");
}

function startNewChat() {
  const sel = document.getElementById("new-chat-user");
  const userId = parseInt(sel.value);
  if (!userId) {
    document.getElementById("new-chat-err").textContent = "Debes seleccionar un usuario";
    document.getElementById("new-chat-err").style.display = "";
    return;
  }
  closeModal("new-chat-modal");
  openConv(userId);
}

// ══════════════════════════════════════════
//  MODAL UTILS
// ══════════════════════════════════════════

function openModal(id) {
  document.getElementById(id).classList.add("open");
}

function closeModal(id) {
  document.getElementById(id).classList.remove("open");
}

document.querySelectorAll(".modal-overlay").forEach((o) => {
  o.addEventListener("click", (e) => {
    if (e.target === o) o.classList.remove("open");
  });
});