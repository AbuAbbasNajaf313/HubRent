"""Registrierung, Login, Logout."""
from __future__ import annotations

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user

from app.domain.errors import DomainError

from . import LoginUser, hubrent, now, safe_next
from .forms import ActionForm, LoginForm, RegisterForm

bp = Blueprint("auth", __name__)


@bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("catalog.devices"))
    form = RegisterForm()
    if form.validate_on_submit():
        try:
            c = hubrent().accounts.register(
                form.email.data, form.full_name.data, form.password.data, form.terms.data, now()
            )
        except DomainError as exc:
            flash(str(exc), "error")
        else:
            login_user(LoginUser(c))
            flash(f"Willkommen bei HubRent, {c.full_name}!", "success")
            return redirect(url_for("catalog.devices"))
    return render_template("auth/register.html", form=form), 200 if request.method == "GET" else 400


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("account.overview"))
    form = LoginForm()
    if request.method == "GET":
        form.next.data = request.args.get("next", "")
    if form.validate_on_submit():
        c = hubrent().accounts.authenticate(form.email.data, form.password.data)
        if c:
            login_user(LoginUser(c))
            flash(f"Hallo {c.full_name}!", "success")
            return redirect(safe_next(form.next.data) or url_for("account.overview"))
        # Absichtlich keine Unterscheidung, ob E-Mail oder Passwort falsch war.
        flash("E-Mail oder Passwort ist falsch.", "error")
    return render_template("auth/login.html", form=form), 200 if request.method == "GET" else 400


@bp.route("/logout", methods=["POST"])
@login_required
def logout():
    if ActionForm().validate_on_submit():
        logout_user()
        flash("Du bist abgemeldet.", "info")
    return redirect(url_for("catalog.index"))
