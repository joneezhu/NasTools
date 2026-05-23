FROM python:3.10.11-slim-bullseye
COPY --from=shinsenter/s6-overlay / /
RUN set -xe && \
    export DEBIAN_FRONTEND="noninteractive" && \
    # apt 网络加固: 重试 + 超时, 避免 deb.debian.org (Fastly CDN) 偶发 connection reset 直接挂掉
    echo 'Acquire::Retries "5";'                       >  /etc/apt/apt.conf.d/80-retries && \
    echo 'Acquire::http::Timeout "60";'                >> /etc/apt/apt.conf.d/80-retries && \
    echo 'Acquire::https::Timeout "60";'               >> /etc/apt/apt.conf.d/80-retries && \
    echo 'Acquire::http::No-Cache "true";'             >> /etc/apt/apt.conf.d/80-retries && \
    apt-get update -y && \
    apt-get install -y --fix-missing wget bash && \
    PKG_LIST="$(wget --no-check-certificate -qO- https://raw.githubusercontent.com/joneezhu/NasTools/master/package_list_debian.txt)" && \
    # 整体最多重试 3 次, 每次失败先 apt-get update 刷镜像 metadata 再装
    APT_OK=0 && for i in 1 2 3; do \
        if apt-get install -y --fix-missing $PKG_LIST; then APT_OK=1; break; fi; \
        echo "[apt] install attempt $i failed, retrying..."; sleep 5; apt-get update -y || true; \
    done && \
    [ "$APT_OK" = "1" ] || { echo "[apt] install failed after 3 attempts"; exit 1; } && \
    ln -sf /command/with-contenv /usr/bin/with-contenv && \
    # zone time
    ln -sf /usr/share/zoneinfo/${TZ} /etc/localtime && \
    echo "${TZ}" > /etc/timezone && \
    # locale
    locale-gen zh_CN.UTF-8 && \
    # chromedriver
    ln -sf /usr/bin/chromedriver /usr/lib/chromium/chromedriver && \
    # Python settings
    update-alternatives --install /usr/bin/python python /usr/local/bin/python3.10 3 && \
    update-alternatives --install /usr/bin/python python /usr/bin/python3.9 2 && \
    update-alternatives --install /usr/bin/python3 python3 /usr/local/bin/python3.10 3 && \
    update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.9 2 && \
    # Rclone
    curl https://rclone.org/install.sh | bash && \
    # Minio
    if [ "$(uname -m)" = "x86_64" ]; then ARCH=amd64; elif [ "$(uname -m)" = "aarch64" ]; then ARCH=arm64; fi && \
    curl https://dl.min.io/client/mc/release/linux-${ARCH}/mc --create-dirs -o /usr/bin/mc && \
    chmod +x /usr/bin/mc && \
    # Pip requirements prepare
    apt-get install -y build-essential && \
    # Pip requirements
    pip install --upgrade pip 'setuptools<70' wheel && \
    pip install cython && \
    pip install -r https://raw.githubusercontent.com/joneezhu/NasTools/master/requirements.txt && \
    # Clear
    apt-get remove -y build-essential && \
    apt-get autoremove -y && \
    apt-get clean -y && \
    rm -rf \
        /tmp/* \
        /root/.cache \
        /var/lib/apt/lists/* \
        /var/tmp/*
ENV S6_SERVICES_GRACETIME=30000 \
    S6_KILL_GRACETIME=60000 \
    S6_CMD_WAIT_FOR_SERVICES_MAXTIME=0 \
    S6_SYNC_DISKS=1 \
    HOME="/nt" \
    TERM="xterm" \
    PATH=${PATH}:/usr/lib/chromium:/command \
    TZ="Asia/Shanghai" \
    NASTOOL_CONFIG="/config/config.yaml" \
    NASTOOL_AUTO_UPDATE=false \
    NASTOOL_CN_UPDATE=true \
    NASTOOL_VERSION=master \
    REPO_URL="https://github.com/joneezhu/NasTools.git" \
    PYPI_MIRROR="https://pypi.tuna.tsinghua.edu.cn/simple" \
    PUID=0 \
    PGID=0 \
    UMASK=000 \
    PYTHONWARNINGS="ignore:semaphore_tracker:UserWarning" \
    WORKDIR="/nas-tools"
WORKDIR ${WORKDIR}
RUN set -xe \
    && mkdir ${HOME} \
    && groupadd -r nt -g 911 \
    && useradd -r nt -g nt -d ${HOME} -s /bin/bash -u 911 \
    && python_ver=$(python3 -V | awk '{print $2}') \
    && echo "${WORKDIR}/" > /usr/local/lib/python${python_ver%.*}/site-packages/nas-tools.pth \
    && echo 'fs.inotify.max_user_watches=5242880' >> /etc/sysctl.conf \
    && echo 'fs.inotify.max_user_instances=5242880' >> /etc/sysctl.conf \
    && echo "nt ALL=(ALL) NOPASSWD: ALL" >> /etc/sudoers \
    && git config --global pull.ff only \
    && git clone -b master ${REPO_URL} ${WORKDIR} --depth=1 --recurse-submodule \
    && git config --global --add safe.directory ${WORKDIR}
COPY --chmod=755 ./rootfs /
EXPOSE 3000
VOLUME [ "/config" ]
ENTRYPOINT [ "/init" ]