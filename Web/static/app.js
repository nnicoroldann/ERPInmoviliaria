/*
 * app.js
 * Lógica de interfaz de ERP Inmobiliarias:
 *  - Toggle de tema día/noche (persistido en localStorage)
 *  - Fondo animado de estrellas (solo modo noche)
 *  - Notificaciones toast (reemplazan el alert ancho)
 *  - Efecto ripple en los botones
 *
 * Nota: el tema inicial se aplica con un script inline en <head>
 * (antes de este archivo) para evitar el "flash" de tema incorrecto.
 */

(function () {
    "use strict";

    var REDUCE_MOTION = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    /* ---------------- Tema día / noche ---------------- */

    function initThemeToggle() {
        var boton = document.getElementById("theme-toggle");
        if (!boton) return;

        function actualizarIcono() {
            var esClaro = document.documentElement.getAttribute("data-theme") === "light";
            boton.innerHTML = esClaro ? ICONO_LUNA : ICONO_SOL;
            boton.setAttribute("aria-label", esClaro ? "Cambiar a modo noche" : "Cambiar a modo día");
            boton.title = boton.getAttribute("aria-label");
        }

        boton.addEventListener("click", function () {
            var actual = document.documentElement.getAttribute("data-theme") === "light" ? "light" : "dark";
            var nuevo = actual === "light" ? "dark" : "light";
            document.documentElement.setAttribute("data-theme", nuevo);
            try { localStorage.setItem("erp-theme", nuevo); } catch (e) { /* almacenamiento no disponible */ }
            actualizarIcono();
        });

        actualizarIcono();
    }

    var ICONO_SOL = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>';
    var ICONO_LUNA = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/></svg>';

    /* ---------------- Fondo de estrellas ---------------- */

    function initEstrellas() {
        var canvas = document.getElementById("estrellas");
        if (!canvas || !canvas.getContext) return;
        var ctx = canvas.getContext("2d");
        var estrellas = [];
        var fugaces = [];
        var ancho, alto, dpr;

        function esModoNoche() {
            return document.documentElement.getAttribute("data-theme") !== "light";
        }

        function generar() {
            dpr = Math.min(window.devicePixelRatio || 1, 2);
            ancho = window.innerWidth;
            alto = window.innerHeight;
            canvas.width = ancho * dpr;
            canvas.height = alto * dpr;
            ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

            var cantidad = Math.round((ancho * alto) / 9000);
            estrellas = [];
            for (var i = 0; i < cantidad; i++) {
                estrellas.push({
                    x: Math.random() * ancho,
                    y: Math.random() * alto,
                    r: Math.random() * 1.3 + 0.3,
                    fase: Math.random() * Math.PI * 2,
                    vel: 0.4 + Math.random() * 0.8,
                    deriva: (Math.random() - 0.5) * 0.02,
                });
            }
        }

        function lanzarFugaz() {
            if (!esModoNoche() || REDUCE_MOTION) return;
            fugaces.push({
                x: Math.random() * ancho * 0.6,
                y: Math.random() * alto * 0.3,
                vx: 6 + Math.random() * 4,
                vy: 3 + Math.random() * 2,
                vida: 1,
            });
            setTimeout(lanzarFugaz, 9000 + Math.random() * 8000);
        }

        function dibujar(t) {
            ctx.clearRect(0, 0, ancho, alto);
            if (esModoNoche()) {
                for (var i = 0; i < estrellas.length; i++) {
                    var e = estrellas[i];
                    var brillo = REDUCE_MOTION ? 0.7 : 0.55 + 0.45 * Math.sin(t * 0.0006 * e.vel + e.fase);
                    ctx.beginPath();
                    ctx.arc(e.x, e.y, e.r, 0, Math.PI * 2);
                    ctx.fillStyle = "rgba(255,255,255," + Math.max(0.08, brillo) + ")";
                    ctx.fill();
                    if (!REDUCE_MOTION) {
                        e.x += e.deriva;
                        if (e.x < 0) e.x = ancho;
                        if (e.x > ancho) e.x = 0;
                    }
                }
                for (var j = fugaces.length - 1; j >= 0; j--) {
                    var f = fugaces[j];
                    ctx.beginPath();
                    var grad = ctx.createLinearGradient(f.x, f.y, f.x - f.vx * 8, f.y - f.vy * 8);
                    grad.addColorStop(0, "rgba(255,255,255,0.9)");
                    grad.addColorStop(1, "rgba(255,255,255,0)");
                    ctx.strokeStyle = grad;
                    ctx.lineWidth = 1.6;
                    ctx.moveTo(f.x, f.y);
                    ctx.lineTo(f.x - f.vx * 8, f.y - f.vy * 8);
                    ctx.stroke();
                    f.x += f.vx;
                    f.y += f.vy;
                    f.vida -= 0.012;
                    if (f.vida <= 0 || f.x > ancho + 50 || f.y > alto + 50) fugaces.splice(j, 1);
                }
            }
            requestAnimationFrame(dibujar);
        }

        generar();
        window.addEventListener("resize", generar);
        requestAnimationFrame(dibujar);
        if (!REDUCE_MOTION) setTimeout(lanzarFugaz, 4000);
    }

    /* ---------------- Toasts ---------------- */

    function crearToast(tipo, mensaje) {
        var cont = document.getElementById("toast-container");
        if (!cont || !mensaje) return;

        var toast = document.createElement("div");
        toast.className = "toast toast-" + (tipo === "error" ? "error" : "ok");

        var icono = document.createElement("span");
        icono.className = "toast-icon";
        icono.textContent = tipo === "error" ? "!" : "✓";

        var texto = document.createElement("span");
        texto.className = "toast-msg";
        texto.textContent = mensaje;

        var cerrar = document.createElement("button");
        cerrar.className = "toast-close";
        cerrar.type = "button";
        cerrar.innerHTML = "&times;";
        cerrar.setAttribute("aria-label", "Cerrar notificación");

        toast.appendChild(icono);
        toast.appendChild(texto);
        toast.appendChild(cerrar);
        cont.appendChild(toast);

        function quitar() {
            toast.classList.add("toast-out");
            setTimeout(function () { toast.remove(); }, 280);
        }

        cerrar.addEventListener("click", quitar);
        setTimeout(quitar, 5000);
    }

    function initToasts() {
        var datos = document.getElementById("toast-data");
        if (datos) {
            var ok = datos.getAttribute("data-ok");
            var error = datos.getAttribute("data-error");
            if (ok) crearToast("ok", ok);
            if (error) crearToast("error", error);

            if ((ok || error) && window.history && window.history.replaceState) {
                var url = new URL(window.location.href);
                url.searchParams.delete("ok");
                url.searchParams.delete("error");
                window.history.replaceState({}, "", url.pathname + url.search + url.hash);
            }
        }

        // Mensajes de error de formularios que se re-renderizan sin
        // redirect (login / registro), pasados por data-attribute.
        var datosForm = document.getElementById("toast-data-form");
        if (datosForm) {
            var errorForm = datosForm.getAttribute("data-error");
            if (errorForm) crearToast("error", errorForm);
        }
    }

    /* ---------------- Ripple en botones ---------------- */

    function initRipple() {
        document.addEventListener("click", function (ev) {
            var btn = ev.target.closest(".btn");
            if (!btn) return;
            var rect = btn.getBoundingClientRect();
            var tam = Math.max(rect.width, rect.height);
            var ripple = document.createElement("span");
            ripple.className = "btn-ripple";
            ripple.style.width = ripple.style.height = tam + "px";
            ripple.style.left = (ev.clientX - rect.left - tam / 2) + "px";
            ripple.style.top = (ev.clientY - rect.top - tam / 2) + "px";
            btn.appendChild(ripple);
            setTimeout(function () { ripple.remove(); }, 600);
        });
    }

    /* ---------------- Resaltar link activo del navbar ---------------- */

    function marcarActivo() {
        var ruta = window.location.pathname;
        document.querySelectorAll(".nav-links a[href]").forEach(function (a) {
            var href = a.getAttribute("href");
            if (href !== "/" && href.length > 1 && ruta.indexOf(href) === 0) {
                a.classList.add("active");
            }
        });
    }

    // Expuesto para páginas que necesitan mostrar un toast fuera del
    // flujo normal de query params (por ej. errores de login/registro
    // que se re-renderizan sin redirect).
    window.mostrarToast = crearToast;

    document.addEventListener("DOMContentLoaded", function () {
        initThemeToggle();
        initEstrellas();
        initToasts();
        initRipple();
        marcarActivo();
    });
})();
