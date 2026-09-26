# CI workflows

Questi workflow sono qui e non in `.github/workflows/` perché il PAT usato per il
push non ha lo scope `workflow`. Per attivarli, spostali manualmente:

```bash
mkdir -p .github/workflows
git mv ci/hassfest.yml .github/workflows/hassfest.yml
git mv ci/hacs.yml .github/workflows/hacs.yml
git commit -m "ci: attiva workflow hassfest + HACS"
git push
```
