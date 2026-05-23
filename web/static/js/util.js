// 进度条配置
NProgress.configure({showSpinner: false});

// replaceAll浏览器兼容
String.prototype.replaceAll = function (s1, s2) {
  return this.replace(new RegExp(s1, "gm"), s2)
}

// 日期时间
Date.prototype.format = function (format) {
  const o = {
    "M+": this.getMonth() + 1, //month
    "d+": this.getDate(), //day
    "h+": this.getHours(), //hour
    "m+": this.getMinutes(), //minute
    "s+": this.getSeconds(), //second
    "q+": Math.floor((this.getMonth() + 3) / 3), //quarter
    "S": this.getMilliseconds() //millisecond
  };
  if (/(y+)/.test(format)) format = format.replace(RegExp.$1,
      (this.getFullYear() + "").substr(4 - RegExp.$1.length));
  for (const k in o)
    if (new RegExp("(" + k + ")").test(format))
      format = format.replace(RegExp.$1,
          RegExp.$1.length === 1 ? o[k] :
              ("00" + o[k]).substr(("" + o[k]).length));
  return format;
}

// Ajax主方法
function ajax_post(cmd, params, handler, aync = true, show_progress = true) {
  if (show_progress) {
    NProgress.start();
  }
  let data = {
    cmd: cmd,
    data: params
  };
  $.ajax({
    type: "POST",
    url: "do?random=" + Math.random(),
    contentType: 'application/json',
    dataType: "json",
    data: JSON.stringify(data),
    cache: false,
    async: aync,
    timeout: 0,
    success: function (data) {
      if (show_progress) {
        NProgress.done();
      }
      if (handler) {
        handler(data);
      }
    },
    error: function (xhr, textStatus, errorThrown) {
      if (show_progress) {
        NProgress.done();
      }
      if (xhr && xhr.status === 200) {
        handler({code: 0});
      }
    }
  });
}

// 备份文件下载
function ajax_backup(handler) {
  const downloadURL = "/backup";
  let xhr = new XMLHttpRequest()
  xhr.open('POST', downloadURL, true);
  xhr.responseType = 'arraybuffer';
  xhr.onload = function () {
    if (this.status === 200) {
      let type = xhr.getResponseHeader('Content-Type')
      let fileName = xhr.getResponseHeader('Content-Disposition')
          .split(';')[1]
          .split('=')[1]
          .replace(/\"/g, '')

      let blob = new Blob([this.response], {type: type})
      if (typeof window.navigator.msSaveBlob !== 'undefined') {
        /*
         * IE workaround for "HTML7007: One or more blob URLs were revoked by closing
         * the blob for which they were created. These URLs will no longer resolve as
         * the data backing the URL has been freed."
         */
        window.navigator.msSaveBlob(blob, fileName);
      } else {
        let URL = window.URL || window.webkitURL;
        let objectUrl = URL.createObjectURL(blob);
        // console.log(objectUrl);
        if (fileName) {
          const a = document.createElement('a');
          // safari doesn't support this yet
          if (typeof a.download === 'undefined') {
            window.location = objectUrl
          } else {
            a.href = objectUrl;
            a.download = fileName;
            document.body.appendChild(a);
            a.click();
            a.remove();
          }
        } else {
          window.location = objectUrl;
        }
      }
    }
    if (handler) {
      handler();
    }
  };
  xhr.send();
}

// 获取链接参数
function getQueryVariable(variable) {
  const query = window.location.search.substring(1);
  const vars = query.split("&");
  for (let i = 0; i < vars.length; i++) {
    const pair = vars[i].split("=");
    if (pair[0] == variable) {
      return pair[1];
    }
  }
  return false;
}

// 鼠标提示等待
function make_cursor_busy() {
  const body = document.querySelector("body");
  body.style.cursor = "wait";
}

// 鼠标取消等待
function cancel_cursor_busy() {
  const body = document.querySelector("body");
  body.style.cursor = "default";
}

// 是否触摸屏设备
function is_touch_device() {
  return 'ontouchstart' in window;
}

function select_name(name) {
  if (name.startsWith("\^")) {
    return `name^=${name.substring(1)}`;
  } else {
    return `name=${name}`;
  }
}

/**
 * 全选按钮绑定
 * @param: btnobj 按钮对象
 * @param: name 被管理checkbox的name
 **/
function select_btn_SelectALL(btnobj, name) {
  if ($(btnobj).text() === "全选") {
    $(`input[${select_name(name)}][type=checkbox]`).prop("checked", true);
    $(btnobj).text("全不选");
  } else {
    $(`input[${select_name(name)}][type=checkbox]`).prop("checked", false);
    $(btnobj).text("全选");
  }
}

/**
 * 全选事件
 * @param: status 全选框状态
 * @param: name 被管理checkbox的name
 **/
function select_SelectALL(status, name) {
  $(`input[${select_name(name)}][type=checkbox]`).prop("checked", status);
}

/**
 * 部分选定事件
 * @param: status 全选框状态
 * @param: name 被管理checkbox的name
 **/
function select_SelectPart(condition, name) {
  $(`input[${select_name(name)}][type=checkbox]`).each(function () {
    if (condition && condition.includes($(this).val())) {
      $(this).prop("checked", true);
    } else {
      $(this).prop("checked", false);
    }
  });
}

/**
 * 获取选中input所有元素value
 * @param: name 被管理checkbox的name
 **/
function select_GetUnselectedVAL(name) {
  let selectedVAL = [];
  $(`input[${select_name(name)}][type=checkbox]`).each(function () {
    if (!($(this).prop("checked"))) {
      selectedVAL.push($(this).val());
    }
  });
  return selectedVAL;
}

/**
 * 获取选中input元素value
 * @param: name 被管理checkbox的name
 **/
function select_GetSelectedVAL(name) {
  let selectedVAL = [];
  $(`input[${select_name(name)}][type=checkbox]`).each(function () {
    if ($(this).prop("checked")) {
      selectedVAL.push($(this).val());
    }
  });
  return selectedVAL;
}

/**
 * 获取隐藏input元素value
 * @param: name 被管理checkbox的name
 **/
function select_GetHiddenVAL(name) {
  let hiddenVAL = [];
  $(`input[${select_name(name)}][type=hidden]`).each(function () {
    hiddenVAL.push($(this).val());
  });
  return hiddenVAL;
}

/**
 * 获取元素下input设置
 * @param: id 元素id
 * @param: prefix 配置前缀
 **/
function input_select_GetVal(id, prefix = null) {
  let params = {};
  $(`#${id} input`).each(function () {
    let key = $(this).attr("id");
    if (key) {
      params[(prefix) ? key.replace(prefix, "") : key] = ($(this).attr("type") === "checkbox") ? !!$(this).prop("checked") : $(this).val();
    }
  });
  $(`#${id} select`).each(function () {
    let key = $(this).attr("id");
    if (key) {
      params[(prefix) ? key.replace(prefix, "") : key] = $(this).val();
    }
  });
  $(`#${id} textarea`).each(function () {
    let key = $(this).attr("id");
    if (key) {
      params[(prefix) ? key.replace(prefix, "") : key] = $(this).val();
    }
  });
  return params;
}

/**
 * 对象数组排序，针对纯英文、数字或纯中文的排序
 * @param: objArr 需要排序的对象数组
 * @param: sortKey  需要进行排序的键
 * @param: sortType asc升序(默认)  desc 降序
 **/
function dictArraySorting(objArr, sortKey, sortType = "asc") {
  return objArr.sort(function (obj1, obj2) {
    let val1 = obj1[sortKey];
    let val2 = obj2[sortKey];
    if (!isNaN(Number(val1)) && !isNaN(Number(val2))) {
      val1 = Number(val1);
      val2 = Number(val2);
    }
    if (sortType === "asc") {
      return val1 - val2;
    } else if (sortType === "desc") {
      return val2 - val1;
    }
  })
}

/**
 * bytes转换为size
 * @param: bytes 字节数
 **/
function bytesToSize(bytes) {
  let size = ''
  if (bytes < 0.1 * 1024) { // 小于0.1KB 则转化成B
    size = bytes + ' B'
  } else if (bytes < 0.1 * 1024 * 1024) { // 小于0.1MB 则转换成KB
    size = (bytes / 1024).toFixed(2) + ' KB'
  } else if (bytes < 0.1 * 1024 * 1024 * 1024) { // 小于0.1GB 则转换成MB
    size = (bytes / (1024 * 1024)).toFixed(2) + ' MB'
  } else if (bytes < 0.1 * 1024 * 1024 * 1024 * 1024) { // 小于0.1TB 则转换成GB
    size = (bytes / (1024 * 1024 * 1024)).toFixed(2) + ' GB'
  } else if (bytes < 0.1 * 1024 * 1024 * 1024 * 1024 * 1024) { // 小于0.1PB 则转换成TB
    size = (bytes / (1024 * 1024 * 1024 * 1024)).toFixed(2) + ' TB'
  } else if (bytes < 0.1 * 1024 * 1024 * 1024 * 1024 * 1024 * 1024) { // 小于0.1EB 则转换成PB
    size = (bytes / (1024 * 1024 * 1024 * 1024 * 1024)).toFixed(2) + ' PB'
  }
  return size
}

/**
 * 暂停
 * @param: ms 暂停毫秒数
 **/
function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

/**
 * 比较版本号大小, v1 大于 v2 时返回 1, 相等返回 0, 小于返回 -1, 主版本相同 commit 不同返回 2
 *
 * 支持的格式:
 *   "v3.4.1"
 *   "v3.4.2-beta.1"   pre-release (alpha < beta < rc < 正式版)
 *   "v3.4.2-rc.2"
 *   "v3.4.1 a112487"  附带 commit 短哈希
 *
 * SemVer 关键规则:
 *   - 正式版 > 任意 pre-release: v3.4.2 > v3.4.2-beta.5 > v3.4.2-beta.1 > v3.4.2-alpha.1
 *   - pre-release 标识符按字典序: alpha < beta < rc
 *   - 同 pre-release 类型按数字: beta.5 > beta.1
 */
function compareVersion(version1, version2) {
  // 分离 commit 短哈希 (空格分隔)
  const parts1 = String(version1 || '').trim().split(/\s+/);
  const parts2 = String(version2 || '').trim().split(/\s+/);
  const c1 = parts1[1] || '';
  const c2 = parts2[1] || '';

  // 拆分主版本与 pre-release 后缀: "3.4.2-beta.1" -> ["3.4.2", "beta.1"]
  const split = (raw) => {
    const s = String(raw || '').replace(/^v/i, '');
    const dashIdx = s.indexOf('-');
    if (dashIdx < 0) return { core: s, pre: '' };
    return { core: s.slice(0, dashIdx), pre: s.slice(dashIdx + 1) };
  };
  const a = split(parts1[0]);
  const b = split(parts2[0]);

  // 主版本号逐位比较
  const v1 = a.core.split('.');
  const v2 = b.core.split('.');
  const len = Math.max(v1.length, v2.length);
  while (v1.length < len) v1.push('0');
  while (v2.length < len) v2.push('0');
  for (let i = 0; i < len; i++) {
    const num1 = parseInt(v1[i], 10) || 0;
    const num2 = parseInt(v2[i], 10) || 0;
    if (num1 > num2) return 1;
    if (num1 < num2) return -1;
  }

  // 主版本相同时, 处理 pre-release: 没 pre 的视为正式版, 大于任何 pre-release
  if (a.pre === '' && b.pre === '') {
    // 两边都是正式版, 比 commit
    if (c1 && c2) return c1 === c2 ? 0 : 2;
    return 0;
  }
  if (a.pre === '' && b.pre !== '') return 1;   // v1 是正式版 > v2 的 pre
  if (a.pre !== '' && b.pre === '') return -1;  // v1 是 pre < v2 的正式版

  // 双方都有 pre, 按 SemVer 逐段比较
  // "beta.1" -> ["beta", "1"]; 数字段按数字, 文本段按字典序; 数字 < 文本
  const p1 = a.pre.split('.');
  const p2 = b.pre.split('.');
  const pLen = Math.max(p1.length, p2.length);
  for (let i = 0; i < pLen; i++) {
    const x = p1[i];
    const y = p2[i];
    if (x === undefined) return -1;  // 短的 pre 较小: beta < beta.1
    if (y === undefined) return 1;
    const xn = /^\d+$/.test(x);
    const yn = /^\d+$/.test(y);
    if (xn && yn) {
      const xi = parseInt(x, 10);
      const yi = parseInt(y, 10);
      if (xi > yi) return 1;
      if (xi < yi) return -1;
    } else if (xn && !yn) {
      return -1;  // 数字段 < 文本段
    } else if (!xn && yn) {
      return 1;
    } else {
      if (x > y) return 1;
      if (x < y) return -1;
    }
  }

  // pre 完全相同, 比 commit
  if (c1 && c2) return c1 === c2 ? 0 : 2;
  return 0;
}


// 计算滚动条相对于页面底部的距离比例
function getScrollRate() {
  const winH = window.innerHeight; //页面可视区域高度
  const pageH = $("#page_content").height(); //页面总高度
  const scrollT = document.body.scrollTop || window.pageYOffset; //滚动条top
  return (pageH - winH - scrollT) / winH;
}

// 判断元素出现滚动条
function hasScrollbar() {
  // 判断是否大于2是因为我观察到部分情况下body可滚动的高度会比可视区域大1
  return (document.body.scrollHeight - (window.innerHeight || document.documentElement.clientHeight)) > 2;
}

// 向浏览器发送通知
function browserNotification(title, text) {
  // 检查浏览器是否支持 Notification API
  if (!("Notification" in window)) {
    return;
  }
  if (!title || !text) {
    return;
  }
  // 请求用户授权显示通知
  let notification;
  let options = {
    body: text.replace(/<br>/g, "\n"),
    icon: "../static/img/logo/logo.png"
  };
  if (Notification.permission === "default") {
    Notification.requestPermission().then(function (permission) {
      if (permission === "granted") {
        // 显示通知
        notification = new Notification(title, options);
      }
    });
  } else if (Notification.permission === "granted") {
    // 显示通知
    notification = new Notification(title, options);
  }
}

// 去除空格
function spaceTrim(val) {
  return val.replace(/(^\s*)|(\s*$)/g, "");
}

// 读取浏览器UA
function set_user_agent(id) {
  let userAgent = navigator.userAgent;
  if (userAgent) {
    $("#" + id).val(userAgent);
  }
}


// 页面刷新
function window_history_refresh() {
  if (window.history.state?.page) {
    navmenu(window.history.state.page, true);
  }
}

//当前页面地址
let CurrentPageUri = "";

// 保存页面历史
function window_history(newflag = false, extra = undefined) {
  const state = {
    title: document.title,
    html: $("#page_content").html(),         // 页面内容
    scroll: $(".page").scrollTop(),  // 页面滚动位置
    CurrentPage: sessionStorage.CurrentPage, // 页面当前页码
    page: CurrentPageUri,                  // 当前页面地址
    extra: extra,                            // 额外的保存数据
  };
  if (newflag) {
    window.history.pushState(state, "");
  } else {
    // 当未传递extra时的页面缓存刷新, 应当重新保留extra数据
    if (!extra && window.history.state?.extra) {
      state.extra = window.history.state.extra;
    }
    window.history.replaceState(state, "");
  }
}

// selectgroup控制单选
function check_selectgroup_raido(obj) {
  // selectgroup控制单选
  let btn_obj = $(obj);
  let status = btn_obj.prop("checked");
  // 当前项未选中则选中,已选中则取消选中
  select_SelectALL(false, btn_obj.attr("name"));
  btn_obj.prop("checked", status);
}

// 滑到指定元素位置
function scroll_to_element(id) {
  if (id) {
    $("html,body").animate({scrollTop: $(`#${id}`).offset().top}, 300);
  }
}
