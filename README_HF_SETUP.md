# Hugging Face Otomatik Deploy Kurulumu

## GitHub Secrets Ayarlanacak:

1. GitHub reposuna git
2. Settings > Secrets and variables > Actions
3. New repository secret ile ekle:

### HF_TOKEN (Hugging Face Token):
- Hugging Face hesabina gir
- Profile > Settings > Access Tokens
- "New token" olustur (write permission)
- Token'i kopyala ve GitHub'a ekle

### SPACE_NAME (Hugging Face Space Adi):
- Format: `kullaniciadi/spacename`
- Örnek: `parapania42/globalmarket`
- GitHub'a ekle

## Calisma Sekli:

1. Kod GitHub'a push edilir
2. GitHub Action otomatik baslar
3. Hugging Face'e deploy eder
4. Space otomatik güncellenir

## Not:
- Dockerfile ve requirements.txt hazir olmali
- Hugging Face Space Docker modunda olmali
