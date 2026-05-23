FROM python:3.10.11-alpine
RUN set -xe \
    && apk add --no-cache --virtual .build-deps \
        libffi-dev \
        gcc \
        musl-dev \
        libxml2-dev \
        libxslt-dev \
    # apk 大批量装包重试 3 次, 兜底 dl-cdn.alpinelinux.org 偶发抖动
    && PKG_LIST="$(wget --no-check-certificate -qO- https://raw.githubusercontent.com/joneezhu/NasTools/master/package_list.txt)" \
    && APK_OK=0 && for i in 1 2 3; do \
           if apk add --no-cache $PKG_LIST; then APK_OK=1; break; fi; \
           echo "[apk] install attempt $i failed, retrying..."; sleep 5; \
       done \
    && [ "$APK_OK" = "1" ] || { echo "[apk] install failed after 3 attempts"; exit 1; } \
    && curl https://rclone.org/install.sh | bash \
    && if [ "$(uname -m)" = "x86_64" ]; then ARCH=amd64; elif [ "$(uname -m)" = "aarch64" ]; then ARCH=arm64; fi \
    && curl https://dl.min.io/client/mc/release/linux-${ARCH}/mc --create-dirs -o /usr/bin/mc \
    && chmod +x /usr/bin/mc \
    # fast-bencode==1.1.3 是上古 sdist, 不兼容 setuptools 70+
    # supervisor 依赖 pkg_resources, setuptools 81+ 已移除, 必须钉 <70 同时满足两个约束
    # 必须先钉死外层 setuptools<70 + pip<25, 再用 --no-build-isolation 让 fast-bencode 复用外层环境
    # (默认 pip 会给每个 sdist 单独建 overlay 装最新 setuptools, 把我们钉的版本架空)
    && pip install --upgrade 'pip<25' 'setuptools<70' wheel cython \
    && pip install --no-build-isolation 'fast-bencode==1.1.3' \
    && pip install -r https://raw.githubusercontent.com/joneezhu/NasTools/master/requirements.txt \
    && apk del --purge .build-deps \
    && rm -rf /tmp/* /root/.cache /var/cache/apk/*
ENV S6_SERVICES_GRACETIME=30000 \
    S6_KILL_GRACETIME=60000 \
    S6_CMD_WAIT_FOR_SERVICES_MAXTIME=0 \
    S6_SYNC_DISKS=1 \
    HOME="/nt" \
    TERM="xterm" \
    PATH=${PATH}:/usr/lib/chromium \
    LANG="C.UTF-8" \
    TZ="Asia/Shanghai" \
    NASTOOL_CONFIG="/config/config.yaml" \
    NASTOOL_AUTO_UPDATE=false \
    NASTOOL_CN_UPDATE=true \
    NASTOOL_VERSION=master \
    PS1="\u@\h:\w \$ " \
    REPO_URL="https://github.com/joneezhu/NasTools.git" \
    PYPI_MIRROR="https://pypi.tuna.tsinghua.edu.cn/simple" \
    ALPINE_MIRROR="mirrors.ustc.edu.cn" \
    PUID=0 \
    PGID=0 \
    UMASK=000 \
    PYTHONWARNINGS="ignore:semaphore_tracker:UserWarning" \
    WORKDIR="/nas-tools"
WORKDIR ${WORKDIR}
RUN mkdir ${HOME} \
    && addgroup -S nt -g 911 \
    && adduser -S nt -G nt -h ${HOME} -s /bin/bash -u 911 \
    && python_ver=$(python3 -V | awk '{print $2}') \
    && python_path=$(which python3) \
    && [ -d "/usr/lib/python${python_ver%.*}/site-packages" ] || mkdir -p "/usr/lib/python${python_ver%.*}/site-packages" \
    && echo "${WORKDIR}/" > /usr/lib/python${python_ver%.*}/site-packages/nas-tools.pth \
    && echo 'fs.inotify.max_user_watches=5242880' >> /etc/sysctl.conf \
    && echo 'fs.inotify.max_user_instances=5242880' >> /etc/sysctl.conf \
    && echo "nt ALL=(ALL) NOPASSWD: ALL" >> /etc/sudoers \
    && git config --global pull.ff only \
    && git clone -b master ${REPO_URL} ${WORKDIR} --depth=1 --recurse-submodule \
    && git config --global --add safe.directory ${WORKDIR}
COPY --chmod=755 ./rootfs /
EXPOSE 3000
VOLUME ["/config"]
ENTRYPOINT [ "/init" ]
