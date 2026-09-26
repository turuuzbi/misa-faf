"use client";

import Link from "next/link";
import { motion } from "framer-motion";
import { ArrowRight, Check, Eye, EyeOff, LockKeyhole, Mail, Sparkles, UserRound } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useAuth } from "@/lib/auth-store";
import { Button, TextInput } from "@/components/ui";

export function AuthShell({ mode }: { mode: "login" | "signup" }) {
  const router = useRouter();
  const { login, signUp } = useAuth();
  const signup = mode === "signup";
  const [username, setUsername] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [identifier, setIdentifier] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [remember, setRemember] = useState(true);
  const [error, setError] = useState("");
  const submit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError("");
    if (signup) {
      if (password !== confirmPassword) { setError("Passwords do not match."); return; }
      const result = await signUp({ username: username.trim().toLowerCase(), displayName, email, password });
      if (!result.ok) { setError(result.error); return; }
    } else {
      const result = await login(identifier, password);
      if (!result.ok) { setError(result.error); return; }
    }
    router.push("/");
  };

  return <main className="flex min-h-[100svh] bg-[#07070a] text-white">
    <div className="relative hidden w-[45%] overflow-hidden border-r border-white/[.07] lg:block"><div className="absolute inset-0 bg-[radial-gradient(circle_at_32%_25%,rgba(155,135,245,.22),transparent_30%),radial-gradient(circle_at_75%_75%,rgba(112,67,170,.18),transparent_31%),linear-gradient(145deg,#0d0d14,#08080b)]" /><div className="relative flex h-full flex-col justify-between p-10 xl:p-16"><Link href="/" className="flex items-center gap-3 text-[15px] font-semibold"><span className="flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-br from-[#c5b8ff] via-[#e11d48] to-[#881337]">M</span>Misa<span className="text-[#fb7185]">.lol</span></Link><div className="max-w-md"><motion.div initial={{ opacity: 0, y: 15 }} animate={{ opacity: 1, y: 0 }}><span className="mb-6 flex h-12 w-12 items-center justify-center rounded-2xl border border-[#b0a1ff]/20 bg-[#e11d48]/10 text-[#b9aeff]"><Sparkles size={21} /></span><h1 className="text-4xl font-semibold leading-[1.05] tracking-[-.055em] xl:text-5xl">Your corner of the internet,<br /><span className="text-[#aa9dff]">made yours.</span></h1><p className="mt-6 max-w-sm text-sm leading-6 text-zinc-400">A beautiful profile, one link, and a little more personality. Welcome to Misa.lol.</p><div className="mt-8 space-y-3 text-sm text-zinc-300">{["Share your whole world in one place", "Make every visit feel personal", "Keep your identity in your hands"].map((item) => <div key={item} className="flex items-center gap-3"><span className="flex h-5 w-5 items-center justify-center rounded-full bg-emerald-400/10 text-emerald-400"><Check size={12} /></span>{item}</div>)}</div></motion.div></div><p className="text-xs text-zinc-600">© 2026 Misa.lol</p></div></div>
    <div className="flex flex-1 items-center justify-center p-5 sm:p-8"><div className="w-full max-w-[420px]"><div className="mb-10 flex items-center gap-3 lg:hidden"><span className="flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-br from-[#c5b8ff] via-[#e11d48] to-[#881337] text-sm font-bold">M</span><span className="text-[15px] font-semibold">Misa<span className="text-[#fb7185]">.lol</span></span></div><div className="mb-8"><p className="mb-3 text-xs font-semibold uppercase tracking-[.18em] text-[#fb7185]">{signup ? "Create your space" : "Welcome back"}</p><h2 className="text-3xl font-semibold tracking-[-.045em]">{signup ? "Create your account" : "Sign in to Misa.lol"}</h2><p className="mt-2 text-sm text-zinc-500">{signup ? "Start building a profile that feels like you." : "Pick up where you left off."}</p></div><form onSubmit={submit} className="space-y-4">{signup && <><div><label htmlFor="username" className="mb-2 block text-xs font-medium text-zinc-400">Username <span className="text-zinc-600">(permanent)</span></label><div className="relative"><UserRound size={15} className="absolute left-3 top-3.5 text-zinc-600" /><TextInput id="username" name="username" autoComplete="username" value={username} onChange={setUsername} placeholder="yourname" className="pl-9" /></div></div><div><label htmlFor="display-name" className="mb-2 block text-xs font-medium text-zinc-400">Display name</label><TextInput id="display-name" name="display-name" autoComplete="name" value={displayName} onChange={setDisplayName} placeholder="Your name" /></div></>}<div><label htmlFor="email" className="mb-2 block text-xs font-medium text-zinc-400">{signup ? "Email address" : "Email or username"}</label><div className="relative"><Mail size={15} className="absolute left-3 top-3.5 text-zinc-600" /><TextInput id="email" name="email" autoComplete={signup ? "email" : "username"} value={signup ? email : identifier} onChange={signup ? setEmail : setIdentifier} placeholder={signup ? "you@example.com" : "you@example.com or username"} type={signup ? "email" : "text"} className="pl-9" /></div></div><div><label htmlFor="password" className="mb-2 block text-xs font-medium text-zinc-400">Password</label><div className="relative"><LockKeyhole size={15} className="absolute left-3 top-3.5 text-zinc-600" /><TextInput id="password" name="password" autoComplete={signup ? "new-password" : "current-password"} value={password} onChange={setPassword} placeholder="••••••••" type={showPassword ? "text" : "password"} className="pl-9 pr-10" /><button type="button" onClick={() => setShowPassword(!showPassword)} className="absolute right-2 top-2 flex h-7 w-7 items-center justify-center rounded-lg text-zinc-600 hover:text-white" aria-label={showPassword ? "Hide password" : "Show password"}>{showPassword ? <EyeOff size={15} /> : <Eye size={15} />}</button></div></div>{signup && <div><label htmlFor="confirm-password" className="mb-2 block text-xs font-medium text-zinc-400">Confirm password</label><TextInput id="confirm-password" name="confirm-password" autoComplete="new-password" value={confirmPassword} onChange={setConfirmPassword} placeholder="••••••••" type="password" /></div>}{!signup && <div className="flex items-center justify-between py-1"><label className="flex items-center gap-2 text-xs text-zinc-500"><input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} className="h-4 w-4 rounded border-white/10 bg-white/[.05] accent-[#e11d48]" />Remember me</label><Link href="#" className="text-xs text-[#b1a5ff] hover:text-white">Forgot password?</Link></div>}{error && <p role="alert" className="rounded-xl border border-red-400/20 bg-red-400/[.06] px-3 py-2.5 text-xs leading-5 text-red-200">{error}</p>}<Button type="submit" variant="accent" className="mt-2 h-12 w-full">{signup ? "Create account" : "Sign in"}<ArrowRight size={16} /></Button></form><p className="mt-8 text-center text-sm text-zinc-500">{signup ? "Already have an account?" : "New to Misa.lol?"}{" "}<Link href={signup ? "/login" : "/signup"} className="font-medium text-[#b1a5ff] hover:text-white">{signup ? "Sign in" : "Create an account"}</Link></p><p className="mt-12 text-center text-[11px] leading-5 text-zinc-700">Frontend demo auth for now. The account layer is isolated so it can be replaced by your real auth provider later.</p></div></div>
  </main>;
}


