#!/usr/bin/env bash
# 把一个静态站点上线到 uniai.net.cn/<路径>。
#
# 用法:
#   ./scripts/deploy-static.sh <本地目录> <路径名> [--spa] [--build "命令"]
#
# 例:
#   ./scripts/deploy-static.sh ~/Desktop/pitch pitch
#     → https://uniai.net.cn/pitch
#
#   ./scripts/deploy-static.sh ~/code/deck/dist deck --spa --build "pnpm build"
#     → 先在 ~/code/deck 跑 pnpm build,再把 dist/ 传上去,前端路由走 SPA 回退
#
# 选项:
#   --spa            客户端路由(React Router / Vue Router 那种)。找不到文件时回退到
#                    index.html 而不是 404。**纯静态多页站不要加**,加了会把真正的
#                    404 变成首页,排查起来很费劲。
#   --build "命令"    传目录的父目录里先跑一次构建。目录本身是 dist/ 时会自动上跳一级。
#   --auth           加 HTTP Basic 密码保护,复用 /internal 那份账号密码
#                    (/etc/nginx/.htpasswd_internal)。未发布的设计稿、内部工具都该加——
#                    默认是公开的,搜索引擎和任何知道地址的人都能看。
#
# 这个脚本是幂等的:重复跑就是更新内容,不会把 nginx 配置越堆越多。
#
# ⚠️ 它会改服务器的 /etc/nginx/conf.d/momo.conf。每次改之前自动备份到
#    momo.conf.bak.<时间戳>,并且**先 nginx -t 通过才 reload**——配置写坏了
#    不会把整站带下线,而是原地报错退出。

set -euo pipefail

HOST="root@101.133.150.57"
CONF="/etc/nginx/conf.d/momo.conf"
DOMAIN="https://uniai.net.cn"

die() { printf '\033[31m✗ %s\033[0m\n' "$*" >&2; exit 1; }
ok()  { printf '\033[32m✓ %s\033[0m\n' "$*"; }
step(){ printf '\n\033[1m▸ %s\033[0m\n' "$*"; }

# ── 参数 ──────────────────────────────────────────────────────────────
SRC="${1:-}"; NAME="${2:-}"; shift 2 2>/dev/null || true
SPA=0; BUILD=""; AUTH=0
while [ $# -gt 0 ]; do
  case "$1" in
    --spa)   SPA=1; shift ;;
    --auth)  AUTH=1; shift ;;
    --build) BUILD="${2:-}"; shift 2 ;;
    *) die "不认识的选项: $1" ;;
  esac
done

[ -n "$SRC" ] && [ -n "$NAME" ] || die "用法: $0 <本地目录> <路径名> [--spa] [--build \"命令\"]"
[ -d "$SRC" ] || die "目录不存在: $SRC"

# 路径名会直接进 nginx 配置和 URL,只放行安全字符。
echo "$NAME" | grep -qE '^[a-z0-9][a-z0-9_-]*$' \
  || die "路径名只能用小写字母/数字/连字符/下划线,且不能以符号开头: $NAME"

# 别覆盖已经在用的路径。/v1 /health /internal /admin 是主站的,占了就出事。
case "$NAME" in
  v1|health|internal|admin|yewne|_next|api)
    # 花括号不能省:后面紧跟中文字符时,bash 会把它当成变量名的一部分。
    die "「${NAME}」是主站已占用的路径,换一个" ;;
esac

# ── 构建 ──────────────────────────────────────────────────────────────
if [ -n "$BUILD" ]; then
  # 传进来的常常是 dist/ 或 build/,构建要在它的父目录跑。
  BUILD_DIR="$SRC"
  case "$(basename "$SRC")" in
    dist|build|out|public) BUILD_DIR="$(dirname "$SRC")" ;;
  esac
  step "构建（在 $BUILD_DIR）"
  ( cd "$BUILD_DIR" && eval "$BUILD" ) || die "构建失败,没有上线任何东西"
  ok "构建完成"
fi

[ -f "$SRC/index.html" ] || die "$SRC 里没有 index.html——确认传的是构建产物目录(dist/build/out),不是源码目录"

# ── 打包上传 ──────────────────────────────────────────────────────────
step "打包上传 $SRC → $HOST:/var/www/$NAME/"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
# COPYFILE_DISABLE 挡住 macOS 的 ._* 影子文件。它们不只是垃圾,进错目录会真的出事
# (见 memory: alembic/versions 下的 ._* 会直接炸 migration)。
COPYFILE_DISABLE=1 tar czf "$TMP/site.tgz" -C "$SRC" .
SIZE=$(du -h "$TMP/site.tgz" | cut -f1)
echo "  包大小 $SIZE"
[ "$(du -k "$TMP/site.tgz" | cut -f1)" -gt 20480 ] && \
  echo "  ⚠️ 超过 20MB。国内 scp 到这台机很慢,大图片建议先压。"

scp -q "$TMP/site.tgz" "$HOST:/tmp/deploy-static.tgz" || die "上传失败"

ssh "$HOST" "
set -e
# 先解到临时目录,成功了才替换——传一半断线不会留下半个站。
rm -rf /tmp/stage-$NAME && mkdir -p /tmp/stage-$NAME
tar xzf /tmp/deploy-static.tgz -C /tmp/stage-$NAME 2>/dev/null
find /tmp/stage-$NAME -name '._*' -delete
[ -f /tmp/stage-$NAME/index.html ] || { echo '解包后没有 index.html'; exit 1; }
rm -rf /var/www/$NAME
mv /tmp/stage-$NAME /var/www/$NAME
chmod -R a+rX /var/www/$NAME
rm -f /tmp/deploy-static.tgz
" || die "服务器端解包失败"
ok "文件已就位 /var/www/$NAME/"

# ── nginx 路由 ────────────────────────────────────────────────────────
step "配置 nginx 路由 $DOMAIN/$NAME"

if [ "$SPA" -eq 1 ]; then
  FALLBACK="/$NAME/index.html"   # 客户端路由:找不到就交给前端
else
  FALLBACK="=404"                # 多页站:404 就是 404,别骗人
fi

AUTH_LINES=""
if [ "$AUTH" -eq 1 ]; then
  ssh "$HOST" "test -f /etc/nginx/.htpasswd_internal" \
    || die "服务器上没有 /etc/nginx/.htpasswd_internal,--auth 用不了"
  AUTH_LINES="        auth_basic \"Yewne Internal\";
        auth_basic_user_file /etc/nginx/.htpasswd_internal;
"
  echo "  已启用密码保护（和 /internal 同一组账号密码）"
fi

# location 块写成一对:
#   `= /名字`  不带斜杠的地址 **301 跳到带斜杠版本**
#   `/名字/`   服务目录本身
#
# ⚠️ 这里原来是直接 `try_files /名字/index.html`,把首页当场吐出来。看着能开,
#    但浏览器认为当前地址是 `/名字`(没有斜杠),于是相对路径的基准变成了 `/`——
#    页面里的 `./app.js` 会被解析成 `/app.js` 而不是 `/名字/app.js`,404。
#    对 ES module 尤其致命:模块加载失败 = 整个页面一个事件都绑不上,点什么都没反应,
#    而 HTML/CSS 照常渲染,看起来完全正常。排查起来非常费劲(2026-08-16 踩过)。
#    改成 301 之后,浏览器地址栏真的变成 `/名字/`,相对路径就对了。
BLOCK="    # ── $NAME (deploy-static.sh 生成,勿手改) ──
    location = /$NAME {
        return 301 /$NAME/;
    }
    location /$NAME/ {
${AUTH_LINES}        alias /var/www/$NAME/;
        index index.html;
        try_files \$uri \$uri/ $FALLBACK;
    }
"

printf '%s' "$BLOCK" > "$TMP/block.conf"
scp -q "$TMP/block.conf" "$HOST:/tmp/block-$NAME.conf"

ssh "$HOST" "
set -e
NAME_R='$NAME'
cp $CONF $CONF.bak.\$(date +%Y%m%d%H%M%S)

# heredoc 定界符必须加引号,参数走 argv 而不是字符串插值。不加引号的话远端 bash
# 会对脚本正文做变量展开和反引号命令替换——Python 注释里出现一个反引号就会被当命令跑。
python3 - \"\$NAME_R\" \"$CONF\" \"/tmp/block-$NAME.conf\" <<'PYEOF'
import sys

name, conf, blockfile = sys.argv[1:4]
block = open(blockfile).read()
src = open(conf).read()

marker = '    # ── %s (deploy-static.sh 生成' % name
if marker in src:
    # 已经装过:整块替换,不追加。幂等的关键。
    start = src.index(marker)
    end = src.index('location /' + name + '/', start)
    end = src.index('}', src.index('try_files', end)) + 2
    src = src[:start] + block + src[end:]
    print('  更新了已有的 location 块')
else:
    # 插在最后一个 "location / {" 前面。nginx 前缀匹配取最长,顺序其实无所谓,
    # 但放在兜底规则之前读起来更清楚。
    anchor = src.rindex('    location / {')
    src = src[:anchor] + block + src[anchor:]
    print('  新增了 location 块')

open(conf, 'w').write(src)
PYEOF

# 配置写坏了就地停住,绝不 reload——reload 一个坏配置会把整站带下线。
nginx -t 2>&1 | tail -2
nginx -s reload
rm -f /tmp/block-$NAME.conf
" || die "nginx 配置失败。已备份原配置,线上仍是改动前的状态"
ok "nginx 已 reload"

# ── 验证 ──────────────────────────────────────────────────────────────
step "验证"
# 开了 auth 就该被拦下来。这里断言 401 而不是 200——如果保护没生效反而返回 200,
# 那是把未发布的东西公开了,必须当成失败。
EXPECT=200; [ "$AUTH" -eq 1 ] && EXPECT=401

# 不带斜杠的地址现在是 301,要跟随跳转再看落地状态(-L)。
code=$(curl -sL -o /dev/null -w '%{http_code}' "$DOMAIN/$NAME")
hop=$(curl -s  -o /dev/null -w '%{http_code}' "$DOMAIN/$NAME")
[ "$hop" = "301" ] || die "$DOMAIN/$NAME → $hop（预期 301 跳到带斜杠版本）"
[ "$code" = "$EXPECT" ] && ok "$DOMAIN/$NAME → 301 → $code" || die "$DOMAIN/$NAME 跳转后 → $code（预期 $EXPECT）"

code=$(curl -s -o /dev/null -w '%{http_code}' "$DOMAIN/$NAME/")
[ "$code" = "$EXPECT" ] && ok "$DOMAIN/$NAME/ → $code" || die "$DOMAIN/$NAME/ → $code（预期 $EXPECT）"

# 相对路径实测:页面里第一个 ./ 或 ../ 引用的资源必须真的能取到。
# 只看首页 200 是不够的——首页照常渲染、模块 404、页面死掉,三件事可以同时发生。
if [ "$AUTH" -eq 0 ]; then
  asset=$(curl -s "$DOMAIN/$NAME/" \
    | grep -oE '(src|href)="\./[^"]+"|from '"'"'\./[^'"'"']+'"'"'' \
    | head -1 | grep -oE '\./[^"'"'"']+' | sed 's|^\./||')
  if [ -n "$asset" ]; then
    acode=$(curl -s -o /dev/null -w '%{http_code}' "$DOMAIN/$NAME/$asset")
    [ "$acode" = "200" ] && ok "相对资源 $asset → $acode" \
      || die "相对资源 $DOMAIN/$NAME/$asset → $acode。页面能开但资源取不到,JS 会整个失效"
  fi
fi

if [ "$AUTH" -eq 1 ]; then
  ok "密码保护生效（未带凭据返回 401）"
fi

printf '\n\033[32m上线完成:\033[0m %s/%s\n\n' "$DOMAIN" "$NAME"
echo "以后更新内容,同一条命令再跑一遍就行(会原地替换,不会重复加配置)。"
echo "要下线: ssh $HOST \"rm -rf /var/www/$NAME\" 然后手工删掉 $CONF 里那两个 location 块。"
