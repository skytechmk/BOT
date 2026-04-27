import TopBar from '@/components/TopBar'
import { MessageCircle, Send, Phone, Mail } from 'lucide-react'

function ContactCard({ href, icon, title, subtitle, desc, color, bg }) {
  return (
    <a 
      href={href} 
      target="_blank" 
      rel="noopener noreferrer"
      className="card p-4 mb-4 flex items-center gap-4"
      style={{ textDecoration: 'none' }}
    >
      <div style={{ width: 48, height: 48, borderRadius: '50%', background: bg, color: color, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
        {icon}
      </div>
      <div>
        <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: '0.08em', color: color, textTransform: 'uppercase', marginBottom: 2 }}>
          {title}
        </div>
        <div style={{ fontSize: 16, fontWeight: 800, color: 'var(--color-text)' }}>
          {subtitle}
        </div>
        <div style={{ fontSize: 12, color: 'var(--color-dim)', marginTop: 2 }}>
          {desc}
        </div>
      </div>
    </a>
  )
}

export default function Support() {
  return (
    <>
      <TopBar title="Support" />
      
      <div className="px-4 pt-4 pb-20">
        <p style={{ color: 'var(--color-dim)', fontSize: '14px', marginBottom: 24, lineHeight: 1.6 }}>
          Need help? Reach out through any of the channels below. We typically respond within a few hours.
        </p>

        <ContactCard 
          href="https://wa.me/41779586845"
          icon={<MessageCircle size={24} />}
          title="WhatsApp"
          subtitle="+41 77 958 6845"
          desc="Tap to open chat"
          color="#25D366"
          bg="rgba(37,211,102,0.15)"
        />

        <ContactCard 
          href="viber://chat?number=41779586845"
          icon={<MessageCircle size={24} />}
          title="Viber"
          subtitle="+41 77 958 6845"
          desc="Tap to open Viber"
          color="#7360F2"
          bg="rgba(115,96,242,0.15)"
        />

        <ContactCard 
          href="https://t.me/s53ctr3"
          icon={<Send size={24} style={{ marginLeft: -2 }} />}
          title="Telegram"
          subtitle="@s53ctr3"
          desc="Direct message"
          color="#29A8E8"
          bg="rgba(41,168,232,0.15)"
        />

        <ContactCard 
          href="tel:+38973760761"
          icon={<Phone size={24} />}
          title="Phone"
          subtitle="+389 73 760 761"
          desc="Call or SMS"
          color="var(--color-gold)"
          bg="rgba(244,162,54,0.15)"
        />

        <ContactCard 
          href="mailto:nikola@skytech.mk"
          icon={<Mail size={24} />}
          title="Email"
          subtitle="nikola@skytech.mk"
          desc="Send an email"
          color="#50b4ff"
          bg="rgba(80,180,255,0.15)"
        />
      </div>
    </>
  )
}
