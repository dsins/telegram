# 📲 telegram — Terminal & AI Agent için Sıfır Bağımlılıklı Telegram Köprüsü

Bilgisayar başından kalktığında terminal işlerini, script'lerini veya **Claude Code** oturumlarını cebinden takip etmen, dosya alman ve **butonlu onay/cevap** vermen için tasarlanmış ultra hafif bir CLI aracı ve AI skill seti.

- **Sıfır bağımlılık:** Sadece standart `python3` kütüphanelerini kullanır (`pip install` yok, ekstra paket yok, tek dosya).
- **Çoklu cihaz & oturum dostu:** Mesaj kuyruğunu tüketmez (Telegram 24 saat tutar); aynı botu istediğin kadar sunucu ve bilgisayarda aynı anda kullanabilirsin. Her mesaj otomatik olarak **`makine · klasör`** başlığıyla gelir.
- **Claude Code Skill'leri dahil:**
  - `/tg` — Sen uzaktayken Claude çalışmaya devam eder, sonucu Telegram'dan yazar, kritik adımlarda (deploy, silme, push vb.) sana Telegram'dan butonlu soru sorup cevabını bekler.
  - `/notification` — Claude kapalıyken bile arka planda (cron ile) çalışan akıllı nöbetçiler kurar (domain düşüşü, site çökmesi, stok/fiyat takibi, iş bitimi vb.) ve olay gerçekleşince Telegram'dan haber verir.

---

## 🚀 Hızlı Kurulum (1 Dakika)

### 1. İndir ve Kur

```bash
git clone git@github.com:dsins/telegram.git
cd telegram
./install.sh
```

> `install.sh` betiği `telegram` komutunu `~/.local/bin/telegram` altına bağlar ve Claude Code için `/tg` ile `/notification` skill'lerini `~/.claude/skills/` altına kopyalar.

### 2. Telegram Botunu Oluştur ve Bağla

1. Telegram'da **[@BotFather](https://t.me/BotFather)**'a git ve `/newbot` yazarak yeni bir bot oluştur (sana bir **HTTP API Token** verecek).
2. Terminalde kurulum komutunu çalıştır:
   ```bash
   telegram setup
   ```
3. İstendiğinde token'ı yapıştır, ardından telefonundan yeni oluşturduğun bota **herhangi bir mesaj** (`merhaba` vb.) gönder.
4. Araç seni otomatik tanıyacak, ayarlarını `~/.config/ds/telegram.json` (`0600` izinli, repo dışı güvenli alan) dosyasına kaydedecek ve telefonuna **"✅ Connected"** mesajı atacak.

> **Başka bir sunucuya/bilgisayara eklerken:** Tekrar uğraşmana gerek yok; ya `~/.config/ds/telegram.json` dosyasını kopyala ya da doğrudan `telegram setup <TOKEN> <CHAT_ID>` komutunu çalıştır.

---

## 💻 CLI Kullanımı (`telegram`)

Herhangi bir terminalden, bash script'inden veya cron görevinden doğrudan çağırabilirsin:

```bash
# 1. Mesaj gönder (düz metin veya pipe ile komut çıktısı)
telegram send "Deploy tamamlandı 🚀"
make test 2>&1 | tail -n 30 | telegram send

# 2. Dosya gönder (rapor, log, ekran görüntüsü vb.)
telegram file rapor.pdf "Haftalık özet raporu"

# 3. Soru sor ve cevabı bekle (butonlu veya serbest yazılı)
# Telefondan butona bastığında veya mesajı yanıtladığında cevabı ekrana basar ve çıkar:
CEVAP=$(telegram ask "Prod'a çıkalım mı?" -o "Evet, çık" -o "Hayır, dur")
echo "Seçilen: $CEVAP"

# Serbest metin cevabı beklemek için (-o olmadan):
telegram ask "Hangi branch deploy edilsin?"

# 4. Son 24 saatte bota yazdığın mesajları listele
telegram list

# 5. Canlı dinleme: yeni mesaj gelene kadar bekle (cursor saklar, 409/ağ hatasında kopmaz, foto/dosya indirir)
telegram wait --cursor ~/.local/state/ds-telegram/cursor.json --download /tmp/tg-inbox
```

> **Not:** Çok uzun metinler sohbeti kirletmemek için otomatik olarak `.txt` dosyası şeklinde gönderilir.

---

## 🤖 Claude Code Skill'leri Nasıl Kullanılır?

`./install.sh` çalıştırdığında iki adet global skill (`~/.claude/skills/`) aktif olur:

### 1. `/tg` — Uzaktan Çalışma ve Onay Modu

Bilgisayar başından kalkarken Claude Code'a şöyle yazman yeterli:

- `/tg testleri çalıştır, hataları düzelt ve sonucu yaz`
- Ya da doğal dille: *"Projeyi derle, bitince telegramdan haber ver, prod'a atmadan önce onay al"*
- Tek başına `/tg` yazarsan: Bota son yazdığın mesajı görev olarak okur ve yapmaya başlar!

**Nasıl çalışır?**
- İş bittiğinde veya önemli aşamalarda sana özet geçer.
- Riskli bir adımda (`git push`, `rm`, migration, deploy) sana Telegram'dan **Evet / Hayır** butonlu soru gönderir ve sen telefondan basana kadar bekler.

### 2. `/notification` — Arka Plan Takipçisi (Cron Watch)

Claude Code'u kapatsan bile çalışmaya devam eden periyodik kontroller kurar:

- `/notification example.com domaini düşerse haber ver`
- `/notification https://sitem.com çökerse veya yavaşlarsa yaz`
- `/notification liste` — Aktif takipleri ve durumlarını gösterir.
- `/notification sil <ad>` — İlgili takibi kaldırır.

**Nasıl çalışır?**
- `~/.local/share/ds-watch/<ad>/check.sh` altında izole bir kontrol script'i oluşturup kullanıcı `crontab`'ına ekler.
- Olay gerçekleştiğinde **🎯**, kontrol 3 kez üst üste hata verirse **⚠️**, iş tamamlandığında ise kendi cron kaydını silip **✅** mesajı gönderir.

---

## ⚙️ Ortam Değişkenleri (Opsiyonel)

| Değişken | Açıklama | Varsayılan |
|---|---|---|
| `DS_TELEGRAM_CONFIG` | Config dosyasının yolu | `~/.config/ds/telegram.json` |
| `TELEGRAM_BOT_TOKEN` | Config yerine env üzerinden token | — |
| `TELEGRAM_CHAT_ID` | Config yerine env üzerinden chat ID | — |
| `TELEGRAM_LABEL` | Mesajların ilk satırındaki kalın başlık | `<hostname> · <klasör_adı>` |

---

## 📁 Repo Yapısı

```text
.
├── telegram.py                  # Sıfır bağımlılıklı ana CLI aracı (Python 3)
├── install.sh                   # PATH ve Claude Code skill kurulum betiği
└── skills/
    ├── tg/SKILL.md              # Claude Code /tg (uzaktan görev & onay) skill'i
    └── notification/SKILL.md    # Claude Code /notification (cron nöbetçi) skill'i
```
