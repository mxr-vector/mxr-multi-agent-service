/**
 * 获取账号验证规则
 * @param isRequired 是否必填
 * @returns 账号验证规则数组
 */
export function getUsernameRules(isRequired = true) {
  return [
    ...(isRequired ? [{ required: true, message: "账号不能为空", trigger: "blur" }] : []),
    { min: 2, message: "账号长度至少2位", trigger: "blur" },
    { max: 12, message: "账号长度最多12位", trigger: "blur" },
  ];
}

/**
 * 获取密码验证规则
 * @param isRequired 是否必填
 * @returns 密码验证规则数组
 */
export function getPasswordRules(isRequired = true) {
  return [
    ...(isRequired ? [{ required: true, message: "密码不能为空", trigger: "blur" }] : []),
    { min: 6, message: "密码长度6-18位", trigger: "blur" },
    { max: 18, message: "密码长度6-18位", trigger: "blur" },
  ];
}

/**
 * 获取手机号验证规则
 * @param isRequired 是否必填
 * @returns 手机号验证规则数组
 */
export function getPhoneRules(isRequired = true) {
  return [
    ...(isRequired ? [{ required: true, message: "手机号不能为空", trigger: "blur" }] : []),
    { len: 11, message: "手机号长度必须是11位", trigger: "blur" },
    { pattern: /^[0-9]{11}$/, message: "手机号必须是11位数字", trigger: "blur" },
  ];
}

/**
 * 获取邮箱验证规则
 * @param isRequired 是否必填
 * @returns 邮箱验证规则数组
 */
export function getEmailRules(isRequired = true) {
  return [
    ...(isRequired ? [{ required: true, message: "邮箱不能为空", trigger: "blur" }] : []),
    {
      pattern: /^[a-zA-Z0-9._-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,6}$/,
      message: "邮箱格式不正确",
      trigger: "blur",
    },
  ];
}

/**
 * 获取验证码验证规则
 * @param isRequired 是否必填
 * @returns 验证码验证规则数组
 */
export function getCaptchaCodeRules(isRequired = true) {
  return [...(isRequired ? [{ required: true, message: "验证码不能为空", trigger: "blur" }] : [])];
}

/**
 * 身份证号加权因子
 */
const ID_CARD_WEIGHTS = [7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2];

/**
 * 身份证号校验码映射表
 */
const ID_CARD_CHECK_CODES = ["1", "0", "X", "9", "8", "7", "6", "5", "4", "3", "2"];

/**
 * 校验身份证号（18位）是否合法
 * 校验规则：前17位加权求和后对11取模，与第18位校验码比对
 * @param id 身份证号
 * @returns 是否合法
 */
export function validateIdCard(id: string): boolean {
  const trimmed = id.trim().toUpperCase();
  if (!/^\d{17}[\dX]$/.test(trimmed)) return false;

  const sum = trimmed
    .slice(0, 17)
    .split("")
    .reduce((acc, d, i) => acc + parseInt(d) * (ID_CARD_WEIGHTS[i] ?? 0), 0);

  return ID_CARD_CHECK_CODES[sum % 11] === trimmed[17];
}

/**
 * 获取身份证号验证规则
 * @param isRequired 是否必填
 * @returns 身份证号验证规则数组
 */
export function getIdCardRules(isRequired = true) {
  return [
    ...(isRequired ? [{ required: true, message: "身份证号不能为空", trigger: "blur" }] : []),
    {
      validator: (_rule: unknown, value: string, callback: (error?: Error) => void) => {
        if (!value) {
          callback();
          return;
        }
        if (!validateIdCard(value)) {
          callback(new Error("身份证号格式不正确"));
          return;
        }
        callback();
      },
      trigger: "blur",
    },
  ];
}
