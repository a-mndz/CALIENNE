// Blank-thread greeting shown after "New Conversation" (replaces the full HomeHero,
// which only appears on a fresh session). Entrance animation is CSS-driven (.greeting-rise)
// and auto-disabled under prefers-reduced-motion.
function displayName(user) {
  const local = user?.email?.split("@")[0];
  if (!local) return null;
  return local
    .split(/[._-]+/)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function NewChatGreeting({ user }) {
  const name = displayName(user);
  return (
    <div className="new-chat-greeting" data-testid="new-chat-greeting">
      <p className="greeting-kicker greeting-rise">New conversation</p>
      <h1 className="greeting-title greeting-rise">
        {name ? `Welcome back, ${name}` : "Welcome back"}
      </h1>
      <p className="greeting-sub greeting-rise">
        What are we pressure testing today? Breaker, Logician, Creative and Judge are ready — type below to open the room.
      </p>
    </div>
  );
}

export default NewChatGreeting;
