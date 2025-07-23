using System;

namespace RailwayReservationSystem.Models
{
    public class UserModel
    {
        public int Id { get; set; }
        public string Name { get; set; }
        public string Email { get; set; }
        public string Password { get; set; }
        public string Role { get; set; }
        
        // Additional properties can be added here as necessary to match the database schema.
    }
}