/* global React */
// Auth.jsx — sign-in and create-account cards, copy verbatim from
// frontend/src/routes/login.tsx and register.tsx.

const { useState } = React;

function Field({ label, error, children }) {
  return (
    <div>
      <label className="block text-sm font-medium mb-1 text-gray-900">{label}</label>
      {children}
      {error && <p className="text-red-500 text-xs mt-1">{error}</p>}
    </div>
  );
}

function TextInput(props) {
  return (
    <input
      {...props}
      className={
        "w-full border border-gray-200 rounded px-3 py-2 text-sm " +
        "focus:outline-none focus:ring-2 focus:ring-blue-600 focus:border-blue-600 " +
        (props.className || "")
      }
    />
  );
}

function PrimaryButton({ disabled, children, ...rest }) {
  return (
    <button
      type="submit"
      disabled={disabled}
      className="w-full bg-blue-600 text-white py-2 rounded text-sm font-medium hover:bg-blue-700 disabled:opacity-50"
      {...rest}
    >
      {children}
    </button>
  );
}

function LoginPage({ onLogin, onGoRegister }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState(null);
  const [touched, setTouched] = useState(false);

  const emailErr = touched && !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)
    ? "Invalid email address" : null;
  const passwordErr = touched && !password ? "Password is required" : null;

  const submit = (e) => {
    e.preventDefault();
    setTouched(true);
    if (emailErr || passwordErr) return;
    setPending(true);
    setTimeout(() => {
      // Fake auth — any valid-looking email + non-empty password passes.
      if (password.length < 4) {
        setError("Invalid email or password.");
        setPending(false);
        return;
      }
      onLogin({ email });
    }, 350);
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50">
      <div className="w-full max-w-md p-8 bg-white rounded-lg shadow">
        <div className="flex items-center gap-2 mb-6">
          <LogoMark size={28} />
          <span className="font-bold text-lg text-gray-900">Stock Market</span>
        </div>
        <h1 className="text-2xl font-bold mb-6 text-gray-900">Sign in</h1>
        {error && (
          <div className="mb-4 p-3 bg-red-50 text-red-700 rounded text-sm">
            {error}
          </div>
        )}
        <form onSubmit={submit} className="space-y-4">
          <Field label="Email" error={emailErr}>
            <TextInput
              type="email"
              placeholder="you@example.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </Field>
          <Field label="Password" error={passwordErr}>
            <TextInput
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </Field>
          <PrimaryButton disabled={pending}>
            {pending ? "Signing in..." : "Sign in"}
          </PrimaryButton>
        </form>
        <p className="mt-4 text-sm text-center text-gray-600">
          No account?{" "}
          <button
            type="button"
            onClick={onGoRegister}
            className="text-blue-600 hover:underline"
          >
            Register
          </button>
        </p>
      </div>
    </div>
  );
}

function RegisterPage({ onRegister, onGoLogin }) {
  const [first, setFirst] = useState("");
  const [last, setLast] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState(null);
  const [touched, setTouched] = useState(false);

  const emailErr = touched && !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)
    ? "Invalid email address" : null;
  const passwordErr = touched && password.length < 8
    ? "Password must be at least 8 characters" : null;

  const submit = (e) => {
    e.preventDefault();
    setTouched(true);
    if (emailErr || passwordErr) return;
    setPending(true);
    setTimeout(() => {
      onRegister({ email });
    }, 350);
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50">
      <div className="w-full max-w-md p-8 bg-white rounded-lg shadow">
        <div className="flex items-center gap-2 mb-6">
          <LogoMark size={28} />
          <span className="font-bold text-lg text-gray-900">Stock Market</span>
        </div>
        <h1 className="text-2xl font-bold mb-6 text-gray-900">Create account</h1>
        {error && (
          <div className="mb-4 p-3 bg-red-50 text-red-700 rounded text-sm">
            Registration failed. Please check your details.
          </div>
        )}
        <form onSubmit={submit} className="space-y-4">
          <div className="grid grid-cols-2 gap-3">
            <Field label="First name">
              <TextInput value={first} onChange={(e) => setFirst(e.target.value)} />
            </Field>
            <Field label="Last name">
              <TextInput value={last} onChange={(e) => setLast(e.target.value)} />
            </Field>
          </div>
          <Field label="Email" error={emailErr}>
            <TextInput
              type="email"
              placeholder="you@example.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </Field>
          <Field label="Password" error={passwordErr}>
            <TextInput
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </Field>
          <PrimaryButton disabled={pending}>
            {pending ? "Creating account..." : "Create account"}
          </PrimaryButton>
        </form>
        <p className="mt-4 text-sm text-center text-gray-600">
          Already have an account?{" "}
          <button
            type="button"
            onClick={onGoLogin}
            className="text-blue-600 hover:underline"
          >
            Sign in
          </button>
        </p>
      </div>
    </div>
  );
}

Object.assign(window, { LoginPage, RegisterPage, Field, TextInput, PrimaryButton });
