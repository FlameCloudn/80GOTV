// 选了文件的槽位变成绿色边框，一眼能看出哪几个已选
  document.querySelectorAll('[data-file-slot]').forEach(function (input) {
    input.addEventListener('change', function () {
      input.closest('.file-slot').classList.toggle('has-file', input.files.length > 0);
    });
  });
