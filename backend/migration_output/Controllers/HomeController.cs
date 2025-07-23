using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using RailwayReservationSystem.Models;

namespace RailwayReservationSystem.Controllers
{
    public class HomeController : Controller
    {
        public IActionResult Index()
        {
            return View();
        }

        [HttpGet]
        [AllowAnonymous]
        public IActionResult Login()
        {
            return View();
        }

        [HttpPost]
        [AllowAnonymous]
        public IActionResult Login(LoginModel loginModel)
        {
            if (ModelState.IsValid)
            {
                // Implement authentication logic here

                return RedirectToAction("Index");
            }

            return View(loginModel);
        }

        [HttpGet]
        [AllowAnonymous]
        public IActionResult Register()
        {
            return View();
        }

        [HttpPost]
        [AllowAnonymous]
        public IActionResult Register(RegisterModel registerModel)
        {
            if (ModelState.IsValid)
            {
                // Implement registration logic here

                return RedirectToAction("Index");
            }

            return View(registerModel);
        }
    }
}