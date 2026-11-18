/* The profile modal (#user-profile-modal), opened from a channel message's avatar (ChatBubbles.create): the picture
enlarged and what GET /api/account/{id} returns. Closes on ×, a backdrop click or Escape. */
class UserProfileModal {
  constructor() {
    this.el = document.getElementById("user-profile-modal");
    this.avatarEl = document.getElementById("user-profile-modal-avatar");
    this.nameEl = document.getElementById("user-profile-modal-name");
    this.usernameEl = document.getElementById("user-profile-modal-username");
    document.getElementById("user-profile-modal-close").addEventListener("click", () => this.close());
    // A backdrop click only (event.target): a click that started inside the panel and bubbled up must not close it.
    this.el.addEventListener("click", (event) => {
      if (event.target === this.el) this.close();
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && !this.el.classList.contains("hidden")) this.close();
    });
  }

  close() {
    this.el.classList.add("hidden");
  }

  async open(userId) {
    this.nameEl.textContent = "";
    this.usernameEl.textContent = "Loading…";
    renderAvatar(this.avatarEl, null, "");
    this.el.classList.remove("hidden");
    let profile;
    try {
      profile = await api(`/api/account/${userId}`);
    } catch (err) {
      this.usernameEl.textContent = err.message;
      return;
    }
    const fullName = [profile.first_name, profile.last_name].filter(Boolean).join(" ");
    renderAvatar(this.avatarEl, profile.avatar_url, profile.initials);
    // With no name set, the username is the main line rather than an empty line above a duplicate.
    this.nameEl.textContent = fullName || profile.username;
    this.usernameEl.textContent = fullName ? `@${profile.username}` : "";
  }
}

const userProfileModal = new UserProfileModal();
