# mywpp

CLI única para trocar wallpaper e importar mídia do DJI, substituindo os scripts
`set-wallpaper` / `next-wallpaper` / `kill-wallpaper` / `sync-dji`.

## Uso

```
mywpp boot            # inicializa o hyprpaper com o próximo wallpaper (usado no exec-once do Hyprland)
mywpp next            # avança para o próximo wallpaper (bind Super+W)
mywpp prev            # volta para o wallpaper anterior
mywpp delete          # remove o wallpaper atual e bloqueia reimportação futura (bind Super+Shift+W)
mywpp delete --keep   # remove o wallpaper atual SEM bloquear — útil quando o arquivo local
                       # corrompeu mas o original no celular está ok: ele volta no próximo syncdji
mywpp syncdji         # importa fotos/vídeos novos do DJI Album do celular via MTP
```

## Estado

- Fila embaralhada e persistida: `~/.local/share/hypr-wallpaper-order` (reembaralha só quando o
  conjunto de arquivos em `~/Imagens/wallpapers` muda)
- Índice atual: `~/.local/share/hypr-wallpaper-idx`
- Lock para serializar `next`/`delete`/`boot`: `~/.local/share/hypr-wallpaper.lock`
- Blacklist do sync-dji (arquivos que não devem ser reimportados): `~/.local/share/dji-sync/deleted.txt`

## Requisitos

- `hyprctl`, `hyprpaper`, `notify-send` (ambiente Hyprland)
- `gio` + PyGObject (`gi`) para o `syncdji` (descoberta do dispositivo MTP)
- `dji-thumbs` no PATH (gera thumbnails de vídeos DJI novos, chamado pelo `syncdji`)

## Instalação

`~/.local/bin/mywpp` é um symlink para `mywpp.sh`, que só resolve o diretório do projeto e
roda `mywpp.py`. Sem sync de dados via git — o `.git` aqui é só para versionar o próprio código.
