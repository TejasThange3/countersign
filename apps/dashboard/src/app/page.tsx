import { Nav } from "@/components/nav";
import { Hero } from "@/components/hero";
import { LiveCall } from "@/components/live-call";
import { Principles } from "@/components/principles";
import { Pipeline } from "@/components/pipeline";
import { Policy } from "@/components/policy";
import { Attacks } from "@/components/attacks";
import { Proof } from "@/components/proof";
import { Footer } from "@/components/footer";

export default function Home() {
  return (
    <>
      <Nav />
      <main>
        <Hero />
        <LiveCall />
        <Principles />
        <Pipeline />
        <Policy />
        <Attacks />
        <Proof />
      </main>
      <Footer />
    </>
  );
}
